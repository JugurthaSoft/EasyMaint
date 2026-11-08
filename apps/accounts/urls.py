from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("connexion/", views.LoginView.as_view(), name="login"),
    path("deconnexion/", views.LogoutView.as_view(), name="logout"),
    path("profil/", views.ProfileView.as_view(), name="profile"),
    path("utilisateurs/", views.UserListView.as_view(), name="user_list"),
    path("utilisateurs/nouveau/", views.UserCreateView.as_view(), name="user_create"),
    path("utilisateurs/<int:pk>/", views.UserUpdateView.as_view(), name="user_update"),
    path("utilisateurs/<int:pk>/mot-de-passe/", views.UserSetPasswordView.as_view(), name="user_password"),
    path("roles/", views.RoleListView.as_view(), name="role_list"),
    path("roles/nouveau/", views.RoleCreateView.as_view(), name="role_create"),
    path("roles/<int:pk>/", views.RoleUpdateView.as_view(), name="role_update"),
    path("journal/", views.AuditListView.as_view(), name="audit_list"),
]
