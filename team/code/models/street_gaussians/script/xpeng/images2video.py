import os
import shutil
from pathlib import Path


def images2video(src_path, log=True):
    src_path = Path(src_path)
    dst_path = src_path.parent / "obj_bound_videos"
    os.system(f"mkdir -p {dst_path}")

    cam_list = []
    for i in os.listdir(src_path):
        if "cam" in i and os.path.isdir(src_path / i):
            cam_list.append(i)

    for cam in cam_list:
        temp_folder = dst_path / cam
        os.system(f"mkdir -p {temp_folder}")

        file_list = sorted(os.listdir(src_path / cam))
        for i, fname in enumerate(file_list):
            if "ipy" in fname:
                continue
            
            if log:
                print(f"Processing {cam} {fname}")
            new_file_name = f'image-{i:05}.png'
            destination_file = temp_folder / new_file_name
            shutil.copyfile(src_path / cam / fname, destination_file)
        
        video_name = "_".join(["video", cam, "obj_bound" + ".mp4" ])
        output_video = dst_path / video_name
        os.system(f"ffmpeg -y -framerate 5 -i {temp_folder}/image-%05d.png -c:v mpeg4 -q:v 2 -b:v 5M -pix_fmt yuv420p {output_video}")
        print(f"[DEBUG] Generating {output_video} complete")
        shutil.rmtree(temp_folder)

if __name__ == "__main__":
    src_path = "/workspace/yangxh7@xiaopeng.com/codes/3dgs/street_gaussians/output/m1/c-ffffbe6f/test1/obj_bound"
    print(src_path)
    images2video(src_path)