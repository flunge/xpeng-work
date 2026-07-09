import os 
import sys


def merge_videos(new_path, mode):
    for m in mode:
        ffmpeg_cmd_1 = '''
            ffmpeg -y \
            -i video_cama_${TARGET}_rgb.mp4 \
            -i video_camb_${TARGET}_rgb.mp4 \
            -i video_camc_${TARGET}_rgb.mp4 \
            -filter_complex "
            [0:v] crop=iw/2:ih:0:0 [left0]; [0:v] crop=iw/2:ih:iw/2:0 [right0];
            [1:v] crop=iw/2:ih:0:0 [left1]; [1:v] crop=iw/2:ih:iw/2:0 [right1];
            [2:v] crop=iw/2:ih:0:0 [left2]; [2:v] crop=iw/2:ih:iw/2:0 [right2]" \
            -map "[left0]" -c:v libx264 video_cama_left.mp4 \
            -map "[right0]" -c:v libx264 video_cama_right.mp4 \
            -map "[left1]" -c:v libx264 video_camb_left.mp4 \
            -map "[right1]" -c:v libx264 video_camb_right.mp4 \
            -map "[left2]" -c:v libx264 video_camc_left.mp4 \
            -map "[right2]" -c:v libx264 video_camc_right.mp4
        '''
        ffmpeg_cmd_2 = '''
        ffmpeg -y -i video_cama_right.mp4 -i video_camb_right.mp4 -i video_camc_right.mp4 -filter_complex "\
        nullsrc=size=3840x1080 [base]; \
        [base][0:v] overlay=shortest=1:x=0:y=0 [tmp1]; \
        [tmp1][1:v] overlay=shortest=1:x=1920:y=0 [tmp2]; \
        [tmp2][2:v] overlay=shortest=1:x=2888:y=0" -c:v mpeg4 -q:v 2 -b:v 5M -pix_fmt yuv420p \
        outputabc_${TARGET}.mp4
        '''
        cmd_3 = "rm video_*_right.mp4; rm video_*_left.mp4"
        os.system(f"cd {new_path}; TARGET={m}; {ffmpeg_cmd_1}")
        os.system(f"cd {new_path}; TARGET={m}; {ffmpeg_cmd_2}")
        os.system(f"cd {new_path}; TARGET={m}; {cmd_3}")


def compare_merged_videos(base_path, new_path, mode):
    output_name = "256" if "output256_origin.mp4" in os.listdir(new_path) else "034"
    base_exp = base_path.split("/")[-1].replace("merged_", "")
    new_exp = new_path.split("/")[-1].replace("merged_", "")
    for m in mode:
        cmd_combine = f'''
            ffmpeg -y -i old_{m}.mp4 -i output{output_name}_{m}.mp4 -filter_complex "[0:v][1:v]vstack=inputs=2" \
                -c:v mpeg4 -q:v 2 -b:v 5M -pix_fmt yuv420p compare_{base_exp}_{new_exp}_{m}.mp4
        '''
        os.system(f"cd {base_path}; cp output{output_name}_{m}.mp4 {new_path}/old_{m}.mp4")
        os.system(f"cd {new_path}; {cmd_combine}")
        os.system(f"cd {new_path}; rm old_{m}.mp4")