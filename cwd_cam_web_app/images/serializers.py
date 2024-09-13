from rest_framework import serializers
from .models import Image, ImageChunk

class ImageChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImageChunk
        fields = '__all__'

class ImageSerializer(serializers.ModelSerializer):
    chunks = ImageChunkSerializer(many=True, read_only=True)

    class Meta:
        model = Image
        fields = '__all__'
