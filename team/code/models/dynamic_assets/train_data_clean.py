import os
import logging
import shutil

logging.basicConfig(level=logging.INFO)

def clean_all_mp4_file_in_dir(root_dir):
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".mp4"):
                mp4_path = os.path.join(root, file)
                logging.info(f"Removing mp4 file: {mp4_path}")                
                os.remove(mp4_path)

        for dir in dirs:
            clean_all_mp4_file_in_dir(os.path.join(root, dir))

# def clean_mask_dir(root_dir):
#     # delete /{root_dir}/*/colmap_processed/masks/
#     all_sub_dir_in_root = []
#     for item in os.listdir(root_dir):
#         item_path = os.path.join(root_dir, item)
#         if os.path.isdir(item_path):
#             all_sub_dir_in_root.append(item_path)

#     for sub_dir in all_sub_dir_in_root:
#         mask_dir = os.path.join(sub_dir, "colmap_processed", "masks")
#         if os.path.exists(mask_dir):
#             logging.info(f"Removing mask directory: {mask_dir}")
#             # remove not empty dir
#             shutil.rmtree(mask_dir)

if __name__ == "__main__":
    root_dir = ""
    clean_all_mp4_file_in_dir(root_dir)
    # clean_mask_dir(root_dir)