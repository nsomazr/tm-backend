from django.urls import path

from .views import (
    AdminCompleteOrderView,
    AdminDownloadInvoiceView,
    AdminDownloadReceiptView,
    AdminEmailInvoiceView,
    AdminEmailReceiptView,
    AdminGenerateInvoiceView,
    AdminGenerateReceiptView,
    AdminPaymentOrderDetailView,
    AdminPaymentOrderListView,
    AdminRefreshOrderView,
    AdminRevenueView,
    CheckoutView,
    MyInvoicesView,
    PaymentOrderStatusView,
    SnippeWebhookView,
)

urlpatterns = [
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("orders/<str:reference>/status/", PaymentOrderStatusView.as_view(), name="order-status"),
    path("invoices/", MyInvoicesView.as_view(), name="my-invoices"),
    path("webhooks/snippe/", SnippeWebhookView.as_view(), name="snippe-webhook"),
    path("admin/revenue/", AdminRevenueView.as_view(), name="admin-revenue"),
    path("admin/orders/", AdminPaymentOrderListView.as_view(), name="admin-orders"),
    path("admin/orders/<str:reference>/", AdminPaymentOrderDetailView.as_view(), name="admin-order-detail"),
    path("admin/orders/<str:reference>/refresh/", AdminRefreshOrderView.as_view(), name="admin-order-refresh"),
    path("admin/orders/<str:reference>/complete/", AdminCompleteOrderView.as_view(), name="admin-order-complete"),
    path(
        "admin/orders/<str:reference>/invoice/generate/",
        AdminGenerateInvoiceView.as_view(),
        name="admin-order-invoice-generate",
    ),
    path(
        "admin/orders/<str:reference>/invoice/download/",
        AdminDownloadInvoiceView.as_view(),
        name="admin-order-invoice-download",
    ),
    path(
        "admin/orders/<str:reference>/invoice/email/",
        AdminEmailInvoiceView.as_view(),
        name="admin-order-invoice-email",
    ),
    path(
        "admin/orders/<str:reference>/receipt/generate/",
        AdminGenerateReceiptView.as_view(),
        name="admin-order-receipt-generate",
    ),
    path(
        "admin/orders/<str:reference>/receipt/download/",
        AdminDownloadReceiptView.as_view(),
        name="admin-order-receipt-download",
    ),
    path(
        "admin/orders/<str:reference>/receipt/email/",
        AdminEmailReceiptView.as_view(),
        name="admin-order-receipt-email",
    ),
]
