import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import Ride

User = get_user_model()

class RideLocationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.ride_id = self.scope['url_route']['kwargs']['ride_id']
        self.room_group_name = f'ride_{self.ride_id}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Send initial ride data
        ride_data = await self.get_ride_data()
        await self.send(text_data=json.dumps({
            'type': 'ride_init',
            'data': ride_data
        }))
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        data = json.loads(text_data)
        message_type = data.get('type')
        
        if message_type == 'driver_location_update':
            # Driver sends their location
            await self.update_driver_location(data)
            
            # Broadcast to all in group (rider sees it)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'location_broadcast',
                    'latitude': data['latitude'],
                    'longitude': data['longitude'],
                    'heading': data.get('heading'),
                    'speed': data.get('speed'),
                }
            )
        
        elif message_type == 'status_update':
            await self.update_ride_status(data)
            
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'status_broadcast',
                    'status': data['status'],
                    'timestamp': data.get('timestamp'),
                }
            )
    
    async def location_broadcast(self, event):
        await self.send(text_data=json.dumps({
            'type': 'driver_location_update',
            'latitude': event['latitude'],
            'longitude': event['longitude'],
            'heading': event.get('heading'),
            'speed': event.get('speed'),
        }))
    
    async def status_broadcast(self, event):
        await self.send(text_data=json.dumps({
            'type': 'ride_status_update',
            'status': event['status'],
            'timestamp': event.get('timestamp'),
        }))
    
    @database_sync_to_async
    def get_ride_data(self):
        try:
            ride = Ride.objects.select_related('driver', 'rider').get(id=self.ride_id)
            return {
                'id': str(ride.id),
                'status': ride.status,
                'pickup_latitude': ride.pickup_latitude,
                'pickup_longitude': ride.pickup_longitude,
                'dropoff_latitude': ride.dropoff_latitude,
                'dropoff_longitude': ride.dropoff_longitude,
                'driver_latitude': ride.current_driver_lat,
                'driver_longitude': ride.current_driver_lng,
                'route_polyline': ride.route_polyline,
                'estimated_duration': ride.estimated_duration,
                'estimated_distance': ride.estimated_distance,
            }
        except Ride.DoesNotExist:
            return None
    
    @database_sync_to_async
    def update_driver_location(self, data):
        try:
            from django.utils import timezone
            ride = Ride.objects.get(id=self.ride_id)
            ride.current_driver_lat = data['latitude']
            ride.current_driver_lng = data['longitude']
            ride.driver_location_updated_at = timezone.now()
            ride.save(update_fields=['current_driver_lat', 'current_driver_lng', 'driver_location_updated_at'])
        except Ride.DoesNotExist:
            pass
    
    @database_sync_to_async
    def update_ride_status(self, data):
        try:
            ride = Ride.objects.get(id=self.ride_id)
            ride.status = data['status']
            ride.save(update_fields=['status'])
        except Ride.DoesNotExist:
            pass
