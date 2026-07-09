import argparse
import os
import numpy as np
import imageio
import PIL.Image as pil
import matplotlib as mpl
import matplotlib.cm as cm
from tqdm import tqdm 


def cvt_depth(args):
    
    scene_dir= args.scene_dir
    video_name= args.video_name

    os.makedirs(scene_dir +'/depth'+'_'+video_name, exist_ok=True)
    
    filenames1=sorted((fn for fn in os.listdir(scene_dir+'/'+video_name) if fn.endswith('.npy')))
    
    # depth_near,depth_far for log depth visualization
    depth_near=0.3
    depth_far=50

    rgbs = []
    for it in tqdm(range(0, len(filenames1))):
        fname = scene_dir+'/'+video_name+'/'+filenames1[it]
        depth_i = np.load(fname)

        mask=(depth_i>20.0)
        depth_i[mask]=0.0
        depth= depth_i
        depth_l=np.log(depth)
        normalizer = mpl.colors.Normalize(vmin= -np.log(depth_far), vmax= -np.log(depth_near)) # reverse log depth range
        mapper = cm.ScalarMappable(norm=normalizer, cmap='jet')
        colormapped_im = (mapper.to_rgba(-depth_l)[:, :, :3] * 255).astype(np.uint8) # reverse log depth
        
        vis_im = pil.fromarray(colormapped_im)
        vis_im.save(scene_dir +'/depth'+'_'+video_name+'/' + str(it).zfill(3)+ '.png')

        rgbs.append(vis_im)
    imageio.mimwrite(scene_dir +'/depth'+'_'+video_name  + '_vis.mp4', rgbs, fps=20, quality=8)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--scene_dir')
    # parser.add_argument('--video_name')
    args = parser.parse_args()

    args.video_name="cam0"
    cvt_depth(args)
    args.video_name="cam2"
    cvt_depth(args)
    args.video_name="cam3"
    cvt_depth(args)
    args.video_name="cam4"
    cvt_depth(args)
    args.video_name="cam5"
    cvt_depth(args)
    args.video_name="cam6"
    cvt_depth(args)
