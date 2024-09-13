from django.urls import path
from .views import ImageListCreate, ImageListView, ImageDownloadView, ImageDeleteView, ImageUpdateView, upscale_image_view

urlpatterns = [
    path('api/images/', ImageListCreate.as_view(), name='image-list-create'),
    path('images/', ImageListView.as_view(), name='image-list-view'),
    path('api/images/<int:pk>/download/<str:method>/', ImageDownloadView.as_view(), name='image-download'),
    path('api/images/<int:pk>/delete/', ImageDeleteView.as_view(), name='image-delete'),
    path('api/images/<str:img_dhash>/update/', ImageUpdateView.as_view(), name='image-update'),
    path('', upscale_image_view, name='image-upscale'),
]

