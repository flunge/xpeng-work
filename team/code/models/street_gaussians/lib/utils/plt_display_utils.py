import os
import matplotlib.pyplot as plt

from lib.models.gaussian_model_actor import GaussianModelActor

def draw_curve_plot_and_save(gaussians, save_dir, debug_obj_id):
    obj_model: GaussianModelActor = getattr(gaussians, debug_obj_id)
    fourier_dc_dict = obj_model.fouriered_dc_list
    
    # draw curve plot by matplotlib and save to local, 
    # the horizontal axis is frame, and the vertical axis is feature value
    # only generate one plot
    # min, max should have two separate lines
    plt.figure()
    plt.plot(list(fourier_dc_dict.keys()), [v["min_feature"] for v in fourier_dc_dict.values()], label="Min Feature")
    plt.plot(list(fourier_dc_dict.keys()), [v["max_feature"] for v in fourier_dc_dict.values()], label="Max Feature")
    plt.xlabel("Frame")
    plt.ylabel("Feature Value")
    plt.title(f"Fourier DC Features")
    plt.legend()
    plt.savefig(os.path.join(save_dir, f"fourier_dc_features_{debug_obj_id}.png"))
    plt.close()

    color_dict = obj_model.color_list

    # draw curve plot by matplotlib and save to local,
    # the horizontal axis is frame, and the vertical axis is feature value
    # only generate one plot
    # min, max should have two separate lines
    plt.figure()
    plt.plot(list(color_dict.keys()), [v["min_color"] for v in color_dict.values()], label="Min Color")
    plt.plot(list(color_dict.keys()), [v["max_color"] for v in color_dict.values()], label="Max Color")
    plt.xlabel("Frame")
    plt.ylabel("Color Value")
    plt.title(f"Color Features")
    plt.legend()
    plt.savefig(os.path.join(save_dir, f"color_features_{debug_obj_id}.png"))
    plt.close()

    # draw the origin feature dc values as histogram
    plt.figure()
    print(obj_model.origin_feature_dc_values)
    print(f"len: {len(obj_model.origin_feature_dc_values)}")
    plt.hist(obj_model.origin_feature_dc_values, bins=50, alpha=0.7)
    plt.xlabel("Feature Value")
    plt.ylabel("Frequency")
    plt.title(f"Origin Feature DC Values")
    plt.savefig(os.path.join(save_dir, f"origin_feature_dc_values_{debug_obj_id}.png"))
    plt.close()