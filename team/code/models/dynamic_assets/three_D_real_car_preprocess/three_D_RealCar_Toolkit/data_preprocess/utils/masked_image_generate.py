import sys
import os
import numpy as np
import logging
from PIL import Image

def generate_masked_image(image: np.ndarray, mask: np.ndarray, image_idx: int) -> np.ndarray:
    # Image shape: (1440, 1920, 3), Mask shape: (1440, 1920)
    """
    Generate a masked image by applying a binary mask to the input image.
    Args:
        image (np.array): The input image array.
        mask (np.array): The binary mask array.
    Returns:
        np.array: The masked image array.
    """
    if image is None or mask is None:
        return None
    
    # print how many 0 in the mask, how many 1 in the mask, how many 255 in the mask
    # print(f"Mask statistics - 0 (before): {np.sum(mask == 0)}, 1: {np.sum(mask == 1)}, 255: {np.sum(mask == 255)}")

    mask = np.array(mask, dtype=bool)
    # print(f"Mask statistics - 0 (after): {np.sum(mask == 0)}, 1: {np.sum(mask == 1)}, 255: {np.sum(mask == 255)}")
    # print(f"Masked image shape: {mask.shape}")

    masked_image = image * mask[..., np.newaxis]

    # if image_idx % 2 == 0:
    #     # revert mask [0, 0, 0] as white mask [255, 255, 255]
    #     # not every 0 will be converted, but all chanel is 0 should be converted
    #     masked_image[~mask] = [255, 255, 255]

    return masked_image

def display_image(image: np.ndarray, title: str = "Image"):
    """
    Display an image using PIL.
    
    Args:
        image (np.array): The image array to display.
        title (str): The title for the displayed image.
    """
    if image is None:
        print("No image to display.")
        return
    img_pil = Image.fromarray(image.astype(np.uint8))
    img_pil.show(title=title)

def output_image(image: np.ndarray, output_path: str):
    """
    Save the masked image to a specified path.
    
    Args:
        image (np.array): The image array to save.
        output_path (str): The path where the image will be saved.
    """
    if image is None:
        print("No image to save.")
        return

    if not os.path.exists(os.path.dirname(output_path)):
        os.makedirs(os.path.dirname(output_path))

    img_pil = Image.fromarray(image.astype(np.uint8))
    img_pil.save(output_path)
    print(f"Image saved to {output_path}")

def process_mask_images(image_dir, image_id=-1, mode="all"):
    """
    Process images and their corresponding masks to generate masked images.
    
    Args:
        image_dir (str): Directory containing the images and masks.
        image_id (str): Identifier for the specific image to process.
        mode (str): Mode of operation, either 'all' for all images or 'single' for a specific image.
    """
    if image_dir is None:
        logging.info("Usage: python script.py <image_dir> <image_id> <mode>")
        logging.info("Modes: 'all' for all images, 'single' for a specific image")
        sys.exit(1)

    if mode is None:
        mode = "single"

    if mode == "all":
        origin_image_dir = os.path.join(image_dir, "images")
        
        all_origin_image_file_name = []
        # scan all images in the directory
        for image_file in os.listdir(origin_image_dir):
            if image_file.endswith(".jpg") or image_file.endswith(".png"):
                if image_file.startswith("frame_"):
                    all_origin_image_file_name.append(image_file)

        logging.info(f"Found {len(all_origin_image_file_name)} images in {origin_image_dir}")

        image_idx = 0
        for image_file_name in all_origin_image_file_name:
            image_path = os.path.join(origin_image_dir, image_file_name)
            mask_path = os.path.join(image_dir, "masks", "sam", image_file_name)
            output_path = os.path.join(image_dir, "masked_images", image_file_name)

            if not os.path.exists(mask_path):
                logging.info(f"Mask {mask_path} not found for {image_file_name}, skipping...")
                continue

            # Load image and mask
            image = np.array(Image.open(image_path))
            mask = np.array(Image.open(mask_path))

            masked_image = generate_masked_image(image, mask, image_idx)
            output_image(masked_image, output_path=output_path)
            image_idx += 1

        logging.info("All images processed.")
    elif mode == "single":
        if image_id is None:
            logging.info("Usage: python script.py <image_dir> <image_id> <mode>")
            logging.info("Mode 'single' requires an image_id.")
            sys.exit(1)
        # image id is number, but image_file_name should be like "frame_00001.jpg"
        image_file_name = f"frame_{int(image_id):05d}.jpg"  

        image_path = os.path.join(image_dir, "images", image_file_name)
        mask_path = os.path.join(image_dir, "masks", "sam", image_file_name)
        output_path = os.path.join(image_dir, "masked_images", image_file_name)

        if image_path is None or mask_path is None:
            logging.info("Usage: python script.py <image_path> <mask_path>")
            sys.exit(1)

        # Load image and mask
        image = np.array(Image.open(image_path))
        mask = np.array(Image.open(mask_path))
        
        # print image and mask information
        logging.info(f"Image shape: {image.shape}, Mask shape: {mask.shape}")
        # print(mask)

        masked_image = generate_masked_image(image, mask, 0)
        # display_image(masked_image, title="Masked Image")
        output_image(masked_image, output_path=output_path)


if __name__ == "__main__":
    # get args from command line if needed
    image_dir = sys.argv[1] if len(sys.argv) > 1 else None
    image_id = sys.argv[2] if len(sys.argv) > 2 else None
    mode = sys.argv[3] if len(sys.argv) > 3 else None

    # Ensure image_id is int and mode is str
    if image_id is None:
        image_id_int = -1
    else:
        try:
            image_id_int = int(image_id)
        except ValueError:
            image_id_int = -1

    if mode is None:
        mode_str = "single"
    else:
        mode_str = str(mode)

    process_mask_images(image_dir, image_id_int, mode_str)
