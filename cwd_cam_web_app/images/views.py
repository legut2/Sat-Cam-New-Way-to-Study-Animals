from django.shortcuts import render
from rest_framework import generics, views, status
from rest_framework.response import Response
from .models import Image, ImageChunk
from .serializers import ImageSerializer, ImageChunkSerializer
from django.views.generic import ListView
from django.http import HttpResponse
import os
import json
import requests
import http.client
import time
from dotenv import load_dotenv
from rest_framework.views import APIView


# Load environment variables from the .env file
load_dotenv()

# Global variable for relay command and interval
photo_requested = False

# Environment variables
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
PROJECT_ID = os.getenv("PROJECT_ID")
DEVICE_ID = os.getenv("DEVICE_ID")

# Token management
access_token = None
token_expiry = time.time()

def get_access_token():
    global access_token, token_expiry
    # Check if the current access token is expired or about to expire
    if access_token is None or time.time() > token_expiry - 30:  # Refresh the token 30 seconds before expiry just to be safe
        conn = http.client.HTTPSConnection("notehub.io")
        payload = f"grant_type=client_credentials&client_id={CLIENT_ID}&client_secret={CLIENT_SECRET}"
        headers = {'content-type': "application/x-www-form-urlencoded"}
        conn.request("POST", "/oauth2/token", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")
        conn.close()
        
        # Parse the response to get the access token and expiry time
        token_data = json.loads(data)
        access_token = token_data['access_token']
        expires_in = token_data['expires_in']  # Time in seconds until the token expires
        token_expiry = time.time() + expires_in

    return access_token

def send_request_photo_command(image_dhash, method_req):
    try:
        token = get_access_token()  # Function to get a new access token
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        # Sending relay command
        data = json.dumps({"body": {"method": method_req,"img_dhash": image_dhash}})
        response = requests.post(
            f'https://api.notefile.net/v1/projects/app:{PROJECT_ID}/devices/dev:{DEVICE_ID}/notes/data.qi',
            headers=headers,
            data=data,
        )
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        return response.status_code
    except Exception as e:
        print(f"An error occurred: {e}")
        return status.HTTP_500_INTERNAL_SERVER_ERROR

from django.db import transaction, OperationalError
from rest_framework import generics, status
from rest_framework.response import Response
from .models import Image, ImageChunk
from .serializers import ImageSerializer
import time

class ImageListCreate(generics.ListCreateAPIView):
    queryset = Image.objects.all()
    serializer_class = ImageSerializer

    def create(self, request, *args, **kwargs):
        data = request.data

        img_dhash = data.get("img_dhash")
        h_dist = data.get("h_dist")
        loc = data.get("loc")
        chunk_index = data.get("chunk_index")
        b64_img_chunk = data.get("b64_img_chunk")
        b64_chunk_total = data.get("b64_chunk_total")

        max_retries = 5  # Maximum number of retries if the database is locked
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    # Scenario 1: Initial image creation without chunks
                    if img_dhash and h_dist is not None and loc:
                        image, created = Image.objects.get_or_create(
                            img_dhash=img_dhash,
                            defaults={'h_dist': h_dist, 'loc': loc}
                        )

                        if created:
                            return Response({'status': 'success', 'message': 'Image created successfully'})
                        else:
                            return Response({'status': 'exists', 'message': 'Image already exists'})

                    # Scenario 2: Handling chunked image upload
                    elif img_dhash and chunk_index is not None and b64_img_chunk:
                        try:
                            image = Image.objects.select_for_update().get(img_dhash=img_dhash)
                        except Image.DoesNotExist:
                            return Response({'status': 'error', 'message': 'Image not found'}, status=status.HTTP_404_NOT_FOUND)

                        # Create or update the chunk
                        ImageChunk.objects.update_or_create(
                            image=image,
                            chunk_index=chunk_index,
                            defaults={'b64_img_chunk': b64_img_chunk}
                        )

                        # Update total chunks if provided
                        if b64_chunk_total and image.b64_chunk_total != b64_chunk_total:
                            image.b64_chunk_total = b64_chunk_total
                            image.save(update_fields=['b64_chunk_total'])

                        # Check if all chunks are received
                        if image.chunks.count() == image.b64_chunk_total:
                            image.assemble_image()
                            return Response({'status': 'success', 'message': 'Image assembled successfully'})
                        else:
                            return Response({'status': 'partial', 'message': f'Chunk {chunk_index+1}/{image.b64_chunk_total} received'})

                    # If neither scenario is correctly matched
                    return Response({'status': 'error', 'message': 'Invalid data provided'}, status=status.HTTP_400_BAD_REQUEST)

            except OperationalError:
                # If the database is locked, wait a bit and retry
                if attempt < max_retries - 1:
                    time.sleep(1)  # Wait for 1 second before retrying
                else:
                    return Response({'status': 'error', 'message': 'Database is locked, please try again later'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

class ImageListView(ListView):
    model = Image
    template_name = 'images/image_list.html'
    context_object_name = 'images'

class ImageDownloadView(views.APIView):
    def get(self, request, pk, method):
        image = Image.objects.get(pk=pk)
        if method == 'cellular':
            # Logic for cellular download
            # url = os.getenv('CELLULAR_DOWNLOAD_URL')
            # Call send_request_photo_command with img_dhash
            response = Response(status=send_request_photo_command(image.img_dhash, "cell"))
        elif method == 'satellite':
            # Logic for satellite download
            url = os.getenv('SATELLITE_DOWNLOAD_URL')
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        
        # response = HttpResponse(image.b64_img, content_type='image/png')
        # response['Content-Disposition'] = f'attachment; filename="{image.img_dhash}.png"'
        # response = Response(status=status.HTTP_200_OK)
        return response

class ImageDeleteView(generics.DestroyAPIView):
    queryset = Image.objects.all()
    serializer_class = ImageSerializer

class ImageUpdateView(APIView):
    def put(self, request, img_dhash):
        try:
            image = Image.objects.get(img_dhash=img_dhash)
            b64_img = request.data.get('b64_img')
            if b64_img:
                image.b64_img = b64_img
                image.save()
                return Response({'status': 'success', 'message': 'Image updated successfully'})
            return Response({'status': 'error', 'message': 'b64_img is required'}, status=status.HTTP_400_BAD_REQUEST)
        except Image.DoesNotExist:
            return Response({'status': 'error', 'message': 'Image not found'}, status=status.HTTP_404_NOT_FOUND)

def upscale_image_view(request):
    images = Image.objects.all()
    response = render(request, 'images/upscale_image.html', {'images': images})
    # response['Cross-Origin-Embedder-Policy'] = 'require-corp'
    # response['Cross-Origin-Opener-Policy'] = 'same-origin'
    return response