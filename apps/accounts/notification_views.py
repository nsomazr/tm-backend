from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import UserNotification
from .notification_serializers import UserNotificationSerializer


class NotificationListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserNotificationSerializer
    pagination_class = None

    def get_queryset(self):
        return UserNotification.objects.filter(user=self.request.user).order_by("-created_at")[:50]


class NotificationUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = UserNotification.objects.filter(user=request.user, is_read=False).count()
        return Response({"count": count})


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        notification = UserNotification.objects.filter(user=request.user, pk=pk).first()
        if not notification:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read"])
        return Response(UserNotificationSerializer(notification).data)


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated = UserNotification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({"updated": updated})
