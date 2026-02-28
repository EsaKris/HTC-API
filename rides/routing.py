from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/rides/(?P<ride_id>[0-9a-f-]+)/$', consumers.RideLocationConsumer.as_asgi()),
]
