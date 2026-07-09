import os
import cv2
import tyro
import pickle
import logging

def check_image(infos):
    ret_list = []
    for image_path in infos:
        try:
            if os.path.exists(image_path) == False:
                log_msg = "{} is not exists!".format(image_path)
                logging.info(log_msg)
                continue
            image = cv2.imread(image_path)
            size = image.shape
            ret_list.append(image_path)
            log_msg = "processed {}".format(image_path)
            logging.info(log_msg)
        except:
            log_msg = "{} is destroyed!".format(image_path)
            logging.info(log_msg)
    return ret_list

def main(input_path: str,
         output_path: str
):
    logging.basicConfig(level=logging.DEBUG, filename="remove_invalid_img.log", filemode="a+",
                        format="%(asctime)-15s %(levelname)-8s %(message)s")

    data_infos = pickle.load(open(input_path, "rb"))
    ret_infos = {}
    if "input_image" in data_infos.keys():
        input_images = check_image(data_infos["input_image"])
        ret_infos["input_image"] = input_images
    else:
        logging.info("input_image not in key!")
    if "edited_image" in data_infos.keys():
        edited_images = check_image(data_infos["edited_image"])
        ret_infos["edited_image"] = edited_images
    else:
        logging.info("edited_image not in key!")
    ret_infos["edit_prompt"] = data_infos["edit_prompt"]
    pickle.dump(ret_infos, open(os.path.join(output_path), "wb"))

if __name__ == "__main__":
    tyro.cli(main)