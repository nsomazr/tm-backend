from django.urls import path

from .views import (
    AdminSubscriptionListView,
    MyPurchasesView,
    MySubscriptionView,
    SubscriptionPlanAdminView,
    SubscriptionPlanListView,
)

urlpatterns = [
    path("plans/", SubscriptionPlanListView.as_view(), name="subscription-plans"),
    path("plans/admin/", SubscriptionPlanAdminView.as_view(), name="subscription-plans-admin"),
    path("me/", MySubscriptionView.as_view(), name="my-subscription"),
    path("purchases/", MyPurchasesView.as_view(), name="my-purchases"),
    path("admin/list/", AdminSubscriptionListView.as_view(), name="admin-subscriptions"),
]
