from django.urls import path

from .views import (
    AdminCompleteOrderView,
    AdminPaymentOrderDetailView,
    AdminPaymentOrderListView,
    AdminRefreshOrderView,
    AdminRevenueView,
    CheckoutView,
    MyInvoicesView,
    PaymentOrderStatusView,
)

urlpatterns = [
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("orders/<str:reference>/status/", PaymentOrderStatusView.as_view(), name="order-status"),
    path("invoices/", MyInvoicesView.as_view(), name="my-invoices"),
    path("admin/revenue/", AdminRevenueView.as_view(), name="admin-revenue"),
    path("admin/orders/", AdminPaymentOrderListView.as_view(), name="admin-orders"),
    path("admin/orders/<str:reference>/", AdminPaymentOrderDetailView.as_view(), name="admin-order-detail"),
    path("admin/orders/<str:reference>/refresh/", AdminRefreshOrderView.as_view(), name="admin-order-refresh"),
    path("admin/orders/<str:reference>/complete/", AdminCompleteOrderView.as_view(), name="admin-order-complete"),
]
