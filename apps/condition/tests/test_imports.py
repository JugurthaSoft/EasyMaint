"""Import de mesures (CSV, Excel) et API capteurs : lecture, correspondance, contrôles, doublons, droits, isolation."""
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.condition import importer
from apps.condition.models import (
    Alert,
    ImportProfile,
    Level,
    Measurement,
    MeasurementImport,
    MeasurementPoint,
    MeasurementSession,
    Parameter,
    Threshold,
    TriggerRule,
)
from apps.core.tenancy import tenant_context
from apps.workforce.models import Technician
from apps.workorders.models import WorkRequest
from conftest import make_equipment, make_user

D = Decimal


@pytest.fixture
def setup_a(tenant_a, equipment_a):
    with tenant_context(tenant_a):
        vel = Parameter.objects.create(code="VIB-V", name="Vitesse vibratoire", unit="mm/s", category="vibration")
        temp = Parameter.objects.create(code="TEMP", name="Température", unit="°C", category="temperature")
        point = MeasurementPoint.objects.create(equipment=equipment_a, code="P1", name="Palier moteur")
        point.parameters.set([vel, temp])
        Threshold.objects.create(point=point, parameter=vel, valid_from=timezone.localdate() - timedelta(days=400),
                                 warning_high=D("2.8"), alarm_high=D("4.5"), critical_high=D("7.1"))
        tech = Technician.objects.create(employee_number="T-004", first_name="Sami", last_name="Ben Ali", hourly_rate=10)
    return {"tenant": tenant_a, "equipment": equipment_a, "point": point, "vel": vel, "temp": temp, "tech": tech}


def stamp(days_ago=0, hour=8):
    value = timezone.localtime() - timedelta(days=days_ago + 1)
    return value.replace(hour=hour, minute=30, second=0, microsecond=0)


def csv_file(lines, name="mesures.csv", encoding="utf-8"):
    return SimpleUploadedFile(name, "\n".join(lines).encode(encoding), content_type="text/csv")


def xlsx_file(rows, name="mesures.xlsx"):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


# --- Lecture -----------------------------------------------------------------------------------

def test_csv_semicolon_and_cp1252_are_read():
    table = importer.read_table(csv_file(["Date;Équipement;Valeur", "01/11/2026;PRS-A1;4,2"], encoding="cp1252"), "a.csv")
    assert table.headers == ["Date", "Équipement", "Valeur"]
    assert table.rows == [(2, ["01/11/2026", "PRS-A1", "4,2"])]


def test_csv_comma_and_empty_lines_are_skipped():
    table = importer.read_table(csv_file(["", "Date,Point,VIB-V", "", "2026-11-01 08:00,P1,3.1"]), "a.csv")
    assert table.headers == ["Date", "Point", "VIB-V"]
    assert [line for line, _cells in table.rows] == [4]


def test_xlsx_is_read_and_xls_refused():
    table = importer.read_table(xlsx_file([["Date", "Point", "Valeur"], [stamp().replace(tzinfo=None), "P1", 4.2]]), "a.xlsx")
    assert table.headers == ["Date", "Point", "Valeur"] and table.rows[0][1][2] == 4.2
    with pytest.raises(ValidationError):
        importer.check_upload(SimpleUploadedFile("old.xls", b"x"))
    with pytest.raises(ValidationError):
        importer.read_table(csv_file(["Date;Point"]), "a.csv")  # aucune ligne de données


def test_dates_and_numbers_are_parsed():
    assert importer.parse_datetime_value("07/11/2025 08:30").strftime("%d/%m/%Y %H:%M") == "07/11/2025 08:30"
    assert importer.parse_datetime_value("2025-11-07T08:30:00+01:00").utcoffset() is not None
    with pytest.raises(ValidationError):
        importer.parse_datetime_value("31/02/2025")
    with pytest.raises(ValidationError):
        importer.parse_datetime_value(timezone.now() + timedelta(days=2))
    assert importer.parse_number("4,25") == D("4.2500")
    assert importer.parse_number(3) == D("3.0000")
    assert importer.parse_number("") is None
    for bad in ("abc", "nan", "1e12"):
        with pytest.raises(ValidationError):
            importer.parse_number(bad)


@pytest.mark.django_db
def test_mapping_is_guessed_for_long_and_wide_layouts(setup_a):
    with tenant_context(setup_a["tenant"]):
        long = importer.guess_mapping(["Date", "Équipement", "Point", "Paramètre", "Valeur", "Matricule", "Commentaire"])
        wide = importer.guess_mapping(["Horodatage", "Point", "VIB-V", "Température (°C)", "Divers"])
    assert long["columns"] == {"date": "Date", "equipment": "Équipement", "point": "Point", "parameter": "Paramètre",
                               "value": "Valeur", "technician": "Matricule", "comment": "Commentaire"}
    assert wide == {"columns": {"date": "Horodatage", "point": "Point"}, "values": {"VIB-V": "VIB-V", "Température (°C)": "TEMP"}}
    assert importer.mapping_problems(long) == [] and importer.mapping_problems(wide) == []
    assert importer.mapping_problems({"columns": {"date": "Date"}, "values": {}})


# --- Analyse -------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_analysis_reports_errors_line_by_line(setup_a):
    day = stamp(2).strftime("%d/%m/%Y %H:%M")
    lines = [
        "Date;Équipement;Point;Paramètre;Valeur;Technicien",
        f"{day};PRS-A1;P1;VIB-V;3,1;T-004",   # 2 : valide
        f"{day};PRS-A1;P9;VIB-V;3,1;",        # 3 : point inconnu
        f"{day};PRS-A1;P1;VISC;3,1;",         # 4 : paramètre inconnu
        "pas une date;PRS-A1;P1;TEMP;60;",   # 5 : date illisible
        f"{day};PRS-A1;P1;TEMP;abc;",         # 6 : valeur invalide
        f"{day};PRS-A1;P1;TEMP;;",            # 7 : valeur manquante
        f"{day};PRS-A1;P1;TEMP;61;X-999",     # 8 : matricule inconnu
        f"{day};PRS-A1;P1;VIB-V;3,1;T-004",   # 9 : doublon de la ligne 2
    ]
    with tenant_context(setup_a["tenant"]):
        table = importer.read_table(csv_file(lines), "a.csv")
        analysis = importer.analyse_table(table, importer.guess_mapping(table.headers))
    assert [error["line"] for error in analysis.errors] == [3, 4, 5, 6, 7, 8]
    assert "P9" in analysis.errors[0]["messages"][0]
    assert len(analysis.new_items) == 1 and analysis.duplicates == 1
    item = analysis.new_items[0]
    assert item.point == setup_a["point"] and item.technician == setup_a["tech"] and item.value == D("3.1")


@pytest.mark.django_db
def test_point_code_alone_must_be_unique(setup_a, tenant_a):
    other = make_equipment(tenant_a, "PRS-A2")
    with tenant_context(tenant_a):
        MeasurementPoint.objects.create(equipment=other, code="P1", name="Autre palier").parameters.set([setup_a["vel"]])
        table = importer.read_table(csv_file(["Date;Point;VIB-V", f"{stamp(1):%d/%m/%Y %H:%M};P1;2"]), "a.csv")
        analysis = importer.analyse_table(table, importer.guess_mapping(table.headers))
    assert analysis.errors and "plusieurs équipements" in analysis.errors[0]["messages"][0]


# --- Exécution -------------------------------------------------------------------------------------

def make_import(s, upload, user, mapping=None):
    with tenant_context(s["tenant"]):
        table = importer.read_table(upload, upload.name)
        upload.seek(0)
        return MeasurementImport.objects.create(
            file=upload, original_name=upload.name, mapping=mapping or importer.guess_mapping(table.headers), created_by=user,
        )


@pytest.mark.django_db
def test_execute_records_like_manual_entry_with_alerts_and_rules(setup_a, admin_a, django_capture_on_commit_callbacks):
    with tenant_context(setup_a["tenant"]):
        TriggerRule.objects.create(name="Vibration en alarme", parameter=setup_a["vel"], min_level="alarm", consecutive=2)
    lines = ["Date;Point;VIB-V;TEMP;Commentaire"]
    for days_ago, vib in ((3, "2,1"), (2, "4,8"), (1, "5,2")):
        lines.append(f"{stamp(days_ago):%d/%m/%Y %H:%M};P1;{vib};{60 + days_ago};Ronde")
    imp = make_import(setup_a, csv_file(lines), admin_a)
    with django_capture_on_commit_callbacks(execute=True), tenant_context(setup_a["tenant"]):
        imp = importer.execute(imp, user=admin_a)
        assert imp.status == MeasurementImport.Status.DONE
        assert (imp.imported, imp.sessions_created, imp.skipped, imp.rejected) == (6, 6, 0, 0)
        # Vibration et température sont de types différents : une tournée chacune, par date.
        kinds = sorted(MeasurementSession.objects.values_list("kind", flat=True))
        assert kinds == ["inspection"] * 3 + ["vibration"] * 3
        assert all(s.source_import_id == imp.pk for s in MeasurementSession.objects.all())
        assert "Ronde" in MeasurementSession.objects.first().observations
        alert = Alert.objects.get(parameter=setup_a["vel"])
        assert alert.level == Level.ALARM and alert.first_measurement.value == D("4.8")
        assert alert.work_request is not None and WorkRequest.objects.count() == 1


@pytest.mark.django_db
def test_reimport_ignores_known_measurements(setup_a, admin_a):
    lines = ["Date;Équipement;Point;Paramètre;Valeur", f"{stamp(1):%d/%m/%Y %H:%M};PRS-A1;P1;VIB-V;2,0"]
    first = make_import(setup_a, csv_file(lines), admin_a)
    with tenant_context(setup_a["tenant"]):
        importer.execute(first, user=admin_a)
    lines.append(f"{stamp(0):%d/%m/%Y %H:%M};PRS-A1;P1;VIB-V;2,2")
    second = make_import(setup_a, csv_file(lines), admin_a)
    with tenant_context(setup_a["tenant"]):
        second = importer.execute(second, user=admin_a)
        assert (second.imported, second.skipped) == (1, 1)
        assert Measurement.objects.count() == 2
        with pytest.raises(ValidationError):
            importer.execute(second, user=admin_a)  # déjà traité
        third = make_import(setup_a, csv_file(lines), admin_a)
        with pytest.raises(ValidationError):
            importer.execute(third, user=admin_a)  # rien de nouveau
        assert Measurement.objects.count() == 2


@pytest.mark.django_db
def test_excel_template_round_trip(setup_a, admin_a):
    with tenant_context(setup_a["tenant"]):
        content = importer.build_template()
    workbook = load_workbook(io.BytesIO(content))
    assert workbook.sheetnames == ["Mesures", "Référentiel", "Techniciens", "Lisez-moi"]
    sheet = workbook["Mesures"]
    assert [c.value for c in sheet[1]] == importer.template_headers()
    assert sheet.max_row == 3  # deux paramètres sur le point : deux exemples
    for row in sheet.iter_rows(min_row=2):
        row[0].value = stamp(1).replace(tzinfo=None)
        row[4].value = 2.5
    buffer = io.BytesIO()
    workbook.save(buffer)
    imp = make_import(setup_a, SimpleUploadedFile("modele.xlsx", buffer.getvalue()), admin_a)
    with tenant_context(setup_a["tenant"]):
        imp = importer.execute(imp, user=admin_a)
        assert imp.imported == 2 and imp.rejected == 0
        assert MeasurementSession.objects.filter(technician=setup_a["tech"]).count() == 2


# --- Écrans -----------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_upload_preview_mapping_profile_and_confirm(client, setup_a, admin_a):
    client.force_login(admin_a)
    assert client.get(reverse("condition:import_list")).status_code == 200
    template = client.get(reverse("condition:import_template"))
    assert template.status_code == 200 and template["Content-Type"].startswith("application/vnd.openxml")
    lines = ["Horodatage;Machine;Pt;Vitesse", f"{stamp(1):%d/%m/%Y %H:%M};PRS-A1;P1;3,0", f"{stamp(1):%d/%m/%Y %H:%M};PRS-A1;P2;1"]
    response = client.post(reverse("condition:import_list"), {"file": csv_file(lines, "collecteur.csv")})
    with tenant_context(setup_a["tenant"]):
        imp = MeasurementImport.objects.get()
    assert response.status_code == 302 and response["Location"] == imp.get_absolute_url()
    detail = client.get(imp.get_absolute_url())
    assert detail.status_code == 200 and detail.context["problems"]  # « Pt » et « Vitesse » non reconnus
    # Correspondance manuelle (index des colonnes), mémorisée comme format.
    client.post(reverse("condition:import_mapping", args=[imp.pk]),
                {"f-date": "0", "f-equipment": "1", "f-point": "2", "h-3": "VIB-V", "profile_name": "Collecteur VX"})
    detail = client.get(imp.get_absolute_url())
    assert not detail.context["problems"]
    assert detail.context["new_count"] == 1 and detail.context["analysis"].rejected == 1
    assert "P2" in detail.content.decode()
    with tenant_context(setup_a["tenant"]):
        profile = ImportProfile.objects.get(name="Collecteur VX")
        assert profile.mapping == {"columns": {"date": "Horodatage", "equipment": "Machine", "point": "Pt"}, "values": {"Vitesse": "VIB-V"}}
    response = client.post(reverse("condition:import_confirm", args=[imp.pk]))
    assert response.status_code == 302
    with tenant_context(setup_a["tenant"]):
        imp.refresh_from_db()
        assert imp.status == "done" and imp.imported == 1 and imp.rejected == 1 and imp.errors[0]["line"] == 3
        assert Measurement.objects.get().value == D("3")
    assert client.get(imp.get_absolute_url()).status_code == 200
    assert client.get(reverse("condition:import_file", args=[imp.pk])).status_code == 200
    # Le format mémorisé s'applique au fichier suivant.
    client.post(reverse("condition:import_list"), {"file": csv_file([lines[0], f"{stamp(0):%d/%m/%Y %H:%M};PRS-A1;P1;3,2"], "j2.csv"),
                                                   "profile": profile.pk})
    with tenant_context(setup_a["tenant"]):
        latest = MeasurementImport.objects.order_by("-pk").first()
        assert latest.profile == profile and latest.mapping == profile.mapping


@pytest.mark.django_db
def test_cancel_and_bad_file(client, setup_a, admin_a):
    client.force_login(admin_a)
    response = client.post(reverse("condition:import_list"), {"file": SimpleUploadedFile("photo.png", b"\x89PNG")})
    assert response.status_code == 200 and response.context["form"].errors
    imp = make_import(setup_a, csv_file(["Date;Point;VIB-V", f"{stamp(1):%d/%m/%Y %H:%M};P1;2"]), admin_a)
    client.post(reverse("condition:import_cancel", args=[imp.pk]))
    with tenant_context(setup_a["tenant"]):
        imp.refresh_from_db()
        assert imp.status == "cancelled" and Measurement.objects.count() == 0
    client.post(reverse("condition:import_confirm", args=[imp.pk]))
    with tenant_context(setup_a["tenant"]):
        assert Measurement.objects.count() == 0


@pytest.mark.django_db
def test_imports_need_capability_and_are_isolated(client, setup_a, admin_a, technician_a, admin_b):
    imp = make_import(setup_a, csv_file(["Date;Point;VIB-V", f"{stamp(1):%d/%m/%Y %H:%M};P1;2"]), admin_a)
    client.force_login(technician_a)
    assert client.get(reverse("condition:import_list")).status_code == 403
    assert client.post(reverse("condition:import_confirm", args=[imp.pk])).status_code == 403
    client.force_login(admin_b)
    assert client.get(imp.get_absolute_url()).status_code == 404
    assert client.get(reverse("condition:import_file", args=[imp.pk])).status_code == 404
    assert client.post(reverse("condition:import_confirm", args=[imp.pk])).status_code == 404


# --- API capteurs -------------------------------------------------------------------------------------

@pytest.fixture
def sensor(tenant_a):
    user = make_user(tenant_a, "technician", "capteurs")
    return user, Token.objects.create(user=user)


def api(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client


@pytest.mark.django_db
def test_api_records_measurements_and_ignores_resend(setup_a, sensor):
    _user, token = sensor
    payload = {"equipment": "prs-a1", "measured_at": stamp(0).isoformat(), "technician": "T-004",
               "values": [{"point": "P1", "parameter": "VIB-V", "value": 5.0}, {"point": "P1", "parameter": "TEMP", "value": "61,5"}]}
    response = api(token).post("/api/v1/mesures/", payload, format="json")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["created"] == 2 and body["kind"] == "inspection"
    assert {m["parameter"]: m["level"] for m in body["measurements"]} == {"VIB-V": "alarm", "TEMP": "unknown"}
    with tenant_context(setup_a["tenant"]):
        session = MeasurementSession.objects.get()
        assert session.source_api and session.technician == setup_a["tech"]
        assert Alert.objects.get().level == Level.ALARM
    again = api(token).post("/api/v1/mesures/", payload, format="json")
    assert again.status_code == 200 and again.json()["skipped"] == 2
    listing = api(token).get("/api/v1/mesures/?parameter=VIB-V")
    assert listing.status_code == 200 and listing.json()["count"] == 1


@pytest.mark.django_db
def test_api_validates_like_manual_entry(setup_a, sensor):
    _user, token = sensor
    base = {"equipment": "PRS-A1", "measured_at": stamp(0).isoformat()}
    cases = [
        {**base, "equipment": "INCONNU", "values": [{"point": "P1", "parameter": "VIB-V", "value": 1}]},
        {**base, "values": [{"point": "P1", "parameter": "VISC", "value": 1}]},
        {**base, "values": [{"point": "P1", "parameter": "VIB-V", "value": "abc"}]},
        {**base, "values": []},
        {**base, "measured_at": (timezone.now() + timedelta(days=1)).isoformat(), "values": [{"point": "P1", "parameter": "VIB-V", "value": 1}]},
        {**base, "kind": "radiographie", "values": [{"point": "P1", "parameter": "VIB-V", "value": 1}]},
    ]
    for payload in cases:
        assert api(token).post("/api/v1/mesures/", payload, format="json").status_code == 400, payload
    with tenant_context(setup_a["tenant"]):
        assert Measurement.objects.count() == 0


@pytest.mark.django_db
def test_api_rights_and_tenant_isolation(setup_a, tenant_b, sensor):
    payload = {"equipment": "PRS-A1", "measured_at": stamp(0).isoformat(), "values": [{"point": "P1", "parameter": "VIB-V", "value": 1}]}
    assert APIClient().post("/api/v1/mesures/", payload, format="json").status_code in (401, 403)
    viewer = make_user(setup_a["tenant"], "management", "direction")
    assert api(Token.objects.create(user=viewer)).post("/api/v1/mesures/", payload, format="json").status_code == 403
    other = make_user(tenant_b, "technician", "capteur_b")
    response = api(Token.objects.create(user=other)).post("/api/v1/mesures/", payload, format="json")
    assert response.status_code == 400  # l'équipement de l'entreprise A est inconnu pour B
    assert api(Token.objects.get(user=other)).get("/api/v1/mesures/").json()["count"] == 0
    with tenant_context(setup_a["tenant"]):
        assert Measurement.objects.count() == 0
    # Le jeton fonctionne aussi pour l'API des équipements.
    assert api(sensor[1]).get("/api/v1/equipements/").json()["count"] == 1


@pytest.mark.django_db
def test_create_api_token_command(admin_a):
    out = io.StringIO()
    call_command("create_api_token", "admin_a", stdout=out)
    key = Token.objects.get(user=admin_a).key
    assert key in out.getvalue()
    call_command("create_api_token", "admin_a", "--renew", stdout=io.StringIO())
    assert Token.objects.get(user=admin_a).key != key
