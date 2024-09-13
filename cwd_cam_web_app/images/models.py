from django.db import models

class Image(models.Model):
    b64_img = models.TextField(blank=True, null=True)
    img_dhash = models.CharField(max_length=255)
    h_dist = models.IntegerField()
    loc = models.CharField(max_length=255)
    b64_chunk_total = models.IntegerField(default=0)
    assembled = models.BooleanField(default=False)

    def __str__(self):
        return self.img_dhash

    def assemble_image(self):
        # This method assembles the image by concatenating all the chunks
        chunks = self.chunks.order_by('chunk_index')  # Fetch related chunks in order
        b64_img_data = ''.join([chunk.b64_img_chunk for chunk in chunks])
        self.b64_img = b64_img_data
        self.assembled = True
        self.save()

class ImageChunk(models.Model):
    image = models.ForeignKey(Image, related_name='chunks', on_delete=models.CASCADE)
    chunk_index = models.IntegerField()
    b64_img_chunk = models.TextField()

    def __str__(self):
        return f'Chunk {self.chunk_index} of {self.image.img_dhash}'