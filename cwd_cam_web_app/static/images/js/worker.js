// import { pipeline } from '@xenova/transformers'; // SLOWER because without webgpu support, but v3 of this library doesn't webpack worker well enough yet
import { pipeline, AutoProcessor, Swin2SRForImageSuperResolution, RawImage } from '@huggingface/transformers'; // in Alpha and worth trying at some point because it utilizes webgpu for performance improvements, but havent been able to get to work

self.addEventListener('message', async (event) => {
  const { payload } = event.data;

  try {
    console.log('Worker received payload:', payload);

    const model = payload.modelQuality === 'low'
      ? 'Xenova/swin2SR-lightweight-x2-64'
      : 'Xenova/swin2SR-realworld-sr-x4-64-bsrgan-psnr';

    console.log('Model selected:', model);

    let upscaler;
    try {
      upscaler = await pipeline('image-to-image', model);
      console.log('Pipeline instantiated:', upscaler);
    } catch (e) {
      console.error('Error instantiating pipeline:', e);
      throw new Error('Pipeline instantiation failed');
    }

    let result;
    try {
      result = await upscaler(payload.imageUrl);
      console.log('Upscaling result:', result);

      if (!result || !result.data) {
        throw new Error('Invalid result from upscaling');
      }

      // Convert the Uint8Array to a base64-encoded JPEG string
      const base64Image = await createBase64Image(result.data, result.width, result.height);
      console.log('Base64 Image:', base64Image);
      
      self.postMessage({
        status: 'complete',
        result: `data:image/jpeg;base64,${base64Image}`,
      });
    } catch (e) {
      console.error('Error during upscaling:', e);
      throw new Error('Upscaling failed');
    }
  } catch (error) {
    console.error('Error in worker:', error);
    self.postMessage({
      status: 'error',
      message: error.message,
    });
  }
});


// // Helper function to create a base64 image from Uint8Array
// async function createBase64Image(data, width, height) {
//     return new Promise((resolve, reject) => {
//       try {
//         const canvas = new OffscreenCanvas(width, height);
//         const ctx = canvas.getContext('2d');
        
//         // Create an ImageData object
//         const imageData = new ImageData(height, width);
        
//         // Copy the data into the ImageData object
//         for (let i = 0; i < data.length; i += 4) {
//           imageData.data[i] = data[i];       // R
//           imageData.data[i + 1] = data[i + 1]; // G
//           imageData.data[i + 2] = data[i + 2]; // B
//           imageData.data[i + 3] = 255;       // A
//         }
        
//         // Put the ImageData object onto the canvas
//         ctx.putImageData(imageData, 0, 0);
        
//         canvas.convertToBlob({ type: 'image/jpeg' }).then(blob => {
//           const reader = new FileReader();
//           reader.onloadend = () => {
//             const base64data = reader.result.split(',')[1];
//             resolve(base64data);
//           };
//           reader.onerror = reject;
//           reader.readAsDataURL(blob);
//         });
//       } catch (error) {
//         reject(error);
//       }
//     });
//   }



// Helper function to create a base64 image from Uint8Array
async function createBase64Image(data, width, height) {
return new Promise((resolve, reject) => {
        try {
            const canvas = new OffscreenCanvas(width, height);
            const ctx = canvas.getContext('2d');
            
            // Create an ImageData object
            const imageData = new ImageData(width, height);
            
            // Copy the data into the ImageData object
            for (let i = 0; i < data.length; i += 3) {
                const j = i / 3 * 4;
                imageData.data[j] = data[i];       // R
                imageData.data[j + 1] = data[i + 1]; // G
                imageData.data[j + 2] = data[i + 2]; // B
                imageData.data[j + 3] = 255;       // A
            }
            
            // Put the ImageData object onto the canvas
            ctx.putImageData(imageData, 0, 0);
            
            canvas.convertToBlob({ type: 'image/jpeg' }).then(blob => {
                const reader = new FileReader();
                reader.onloadend = () => {
                const base64data = reader.result.split(',')[1];
                resolve(base64data);
                };
                reader.onerror = reject;
                reader.readAsDataURL(blob);
        });
        } catch (error) {
            reject(error);
        }
    });
}