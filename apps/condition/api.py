"""
API des mesures : `/api/v1/mesures/`.

- GET : dernières mesures (filtres `equipment`, `point`, `parameter`, `since` AAAA-MM-JJ), paginées.
- POST : une tournée envoyée par un capteur, une passerelle ou un logiciel d'appareil :

      {"equipment": "CMP-02", "measured_at": "2026-11-07T08:30:00+01:00",
       "kind": "vibration", "technician": "T-004", "observations": "",
       "values": [{"point": "P1", "parameter": "VIB-V", "value": 4.2}]}

  Mêmes contrôles et mêmes effets que la saisie manuelle (niveaux, alertes, règles).
  Une mesure déjà connue (même point, même paramètre, même date) est ignorée : un envoi
  répété par erreur ne crée pas de doublon.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext
from rest_framework import serializers, status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from apps.accounts.permissions import HasCapability
from apps.core.api import TenantAPIMixin

from . import importer, services
from .models import Measurement

MAX_VALUES = 500


class MeasurementSerializer(serializers.ModelSerializer):
    equipment = serializers.CharField(source="point.equipment.code")
    point = serializers.CharField(source="point.code")
    parameter = serializers.CharField(source="parameter.code")
    unit = serializers.CharField(source="parameter.unit")
    level_label = serializers.CharField(source="get_level_display")
    session = serializers.IntegerField(source="session_id")

    class Meta:
        model = Measurement
        fields = ["id", "session", "measured_at", "equipment", "point", "parameter", "value", "unit", "level", "level_label"]


class ValueInput(serializers.Serializer):
    point = serializers.CharField(max_length=30)
    parameter = serializers.CharField(max_length=30)
    value = serializers.CharField(max_length=40)


class SessionInput(serializers.Serializer):
    equipment = serializers.CharField(max_length=30)
    measured_at = serializers.DateTimeField()
    kind = serializers.CharField(max_length=40, required=False, allow_blank=True)
    technician = serializers.CharField(max_length=30, required=False, allow_blank=True)
    observations = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    values = ValueInput(many=True, allow_empty=False)

    def validate_measured_at(self, value):
        if value > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError(gettext("La date des mesures ne peut pas être dans le futur."))
        return value.replace(microsecond=0)

    def validate_values(self, value):
        if len(value) > MAX_VALUES:
            raise serializers.ValidationError(gettext("%(n)s valeurs au plus par envoi.") % {"n": MAX_VALUES})
        return value


def _messages(exc):
    return list(getattr(exc, "messages", [str(exc)]))


class MeasurementAPIView(TenantAPIMixin, ListAPIView):
    permission_classes = [HasCapability]
    read_capability = "condition.view"
    write_capability = "condition.record"
    serializer_class = MeasurementSerializer

    def get_queryset(self):
        queryset = Measurement.objects.select_related("point__equipment", "parameter").order_by("-measured_at", "-pk")
        params = self.request.query_params
        if params.get("equipment"):
            queryset = queryset.filter(point__equipment__code__iexact=params["equipment"])
        if params.get("point"):
            queryset = queryset.filter(point__code__iexact=params["point"])
        if params.get("parameter"):
            queryset = queryset.filter(parameter__code__iexact=params["parameter"])
        since = parse_date(params.get("since") or "")
        if since:
            queryset = queryset.filter(measured_at__date__gte=since)
        return queryset

    def post(self, request):
        payload = SessionInput(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        resolver = importer.Resolver()
        errors = {}
        try:
            equipment = resolver.find_equipment(data["equipment"])
        except DjangoValidationError as exc:
            return Response({"equipment": _messages(exc)}, status=status.HTTP_400_BAD_REQUEST)
        technician = kind = None
        try:
            if data.get("technician"):
                technician = resolver.find_technician(data["technician"])
        except DjangoValidationError as exc:
            errors["technician"] = _messages(exc)
        try:
            if data.get("kind"):
                kind = importer.parse_kind(data["kind"])
        except DjangoValidationError as exc:
            errors["kind"] = _messages(exc)
        values, value_errors = [], []
        for position, row in enumerate(data["values"]):
            try:
                point = resolver.find_point(row["point"], equipment)
                parameter = resolver.find_parameter(row["parameter"], point)
                value = importer.parse_number(row["value"])
                if value is None:
                    raise DjangoValidationError(gettext("Valeur manquante."))
            except DjangoValidationError as exc:
                value_errors.append({"index": position, "errors": _messages(exc)})
                continue
            values.append((point, parameter, value))
        if value_errors:
            errors["values"] = value_errors
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        measured_at = data["measured_at"]
        existing = set(
            Measurement.objects.filter(point__equipment=equipment, measured_at=measured_at)
            .values_list("point_id", "parameter_id")
        )
        seen, new_values = set(), []
        for point, parameter, value in values:
            key = (point.pk, parameter.pk)
            if key in existing or key in seen:
                continue
            seen.add(key)
            new_values.append((point, parameter, value))
        skipped = len(values) - len(new_values)
        if not new_values:
            return Response({"session": None, "created": 0, "skipped": skipped, "measurements": []}, status=status.HTTP_200_OK)
        try:
            with transaction.atomic():
                session = services.record_session(
                    equipment=equipment, kind=kind or importer.kind_for([p for _pt, p, _v in new_values]),
                    measured_at=measured_at, values=new_values, user=request.user, technician=technician,
                    observations=data.get("observations", ""), source_api=True,
                )
        except DjangoValidationError as exc:
            return Response({"non_field_errors": _messages(exc)}, status=status.HTTP_400_BAD_REQUEST)
        measurements = session.measurements.select_related("point__equipment", "parameter").order_by("pk")
        return Response({
            "session": session.pk, "kind": session.kind, "created": len(new_values), "skipped": skipped,
            "measurements": MeasurementSerializer(measurements, many=True).data,
        }, status=status.HTTP_201_CREATED)


