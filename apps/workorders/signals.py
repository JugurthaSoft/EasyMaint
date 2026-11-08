"""
Signaux du module interventions.

`work_order_closed` est émis quand un OT est validé ou annulé (argument `outcome` :
"validated" ou "cancelled"). Le module préventif s'en sert pour recalculer la
prochaine échéance d'un plan, sans que ce module-ci ait à le connaître.
"""
from django.dispatch import Signal

work_order_closed = Signal()
