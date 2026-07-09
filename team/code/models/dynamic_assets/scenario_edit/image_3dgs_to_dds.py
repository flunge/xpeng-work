import os
import argparse
import logging
from MsgBinder.msg.camera_service.camera_video import CameraVideo
from MsgBinder.msg.camera_service.camera_image import CameraImage
import sqlite3
import subprocess
import numpy as np
import cv2
import time
import scenario_info_update, dds_downloader

logging.basicConfig(level=logging.INFO)

# enum SensorID {
#    CAMERA_FRONT_MAIN = 1,     // not use for orin platform
#    CAMERA_FRONT_NARROW = 2,   // AR0820: port C 2
#    CAMERA_FRONT_FISHEYE = 3,  // AR0820: port C 3
#    CAMERA_FRONT_RIGHT = 4,    // IMX623: port A 1
#    CAMERA_FRONT_LEFT = 5,     // IMX623: port B 4
#    CAMERA_REAR_RIGHT = 6,     //  : port B 2
#    CAMERA_REAR_LEFT = 7,      // 0138: port B 3
#    CAMERA_REAR_MAIN = 8,      // 0220: port C 2
# }
sensor_2_cam_type = {
    2: 0, # fps: 12
    3: 2, # fps: 24
    4: 4, # fps: 12
    5: 3, # fps: 12
    6: 6, # fps: 12
    7: 5, # fps: 12
    8: 7, # fps: 12
}

CAMERA_CONFIG = {
    0: {"width": 1920, "height": 1080, "bitrate_kbps": 83819, "fps": 25, "img_fps": 12, "image_width": 512, "image_height": 384}, # camera_front_narrow
    2: {"width": 1920, "height": 1080, "bitrate_kbps": 80738, "fps": 25, "img_fps": 24, "image_width": 512, "image_height": 384}, # camera_front_fisheye
    3: {"width": 968,  "height": 774,  "bitrate_kbps": 31300, "fps": 25, "img_fps": 12, "image_width": 512, "image_height": 384}, # camera_front_right
    4: {"width": 968,  "height": 774,  "bitrate_kbps": 31283, "fps": 25, "img_fps": 12, "image_width": 512, "image_height": 384}, # camera_front_right
    5: {"width": 968,  "height": 774,  "bitrate_kbps": 31024, "fps": 25, "img_fps": 12, "image_width": 512, "image_height": 384}, # camera_front_left
    6: {"width": 968,  "height": 774,  "bitrate_kbps": 31306, "fps": 25, "img_fps": 12, "image_width": 512, "image_height": 384}, # camera_rear_right
    7: {"width": 914,  "height": 474,  "bitrate_kbps": 16773, "fps": 25, "img_fps": 12, "image_width": 512, "image_height": 384}, # camera_rear_left
}

all_timestamps_in_cam = dict()

class DiscoverySqlLiteReader:
    def __init__(self, dat_path):
        self.dat_path = dat_path
        self.conn = sqlite3.connect(self.dat_path)
        self.cursor = self.conn.cursor()

    def get_all_table_names(self):
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = self.cursor.fetchall()
        return [table[0] for table in tables]

    def insert_sim_camera_image_topic_table(self):
        # check SimCameraImageTopicOnWebviz exists
        self.cursor.execute("SELECT COUNT(*) FROM DCPSChannelMsgType WHERE Channel_name = ?;", ("SimCameraImageTopicOnWebviz",))
        exists = self.cursor.fetchone()[0] > 0
        if exists:
            logging.info("Table SimCameraImageTopicOnWebviz already exists.")
            return

        # insert to table: DCPSChannelMsgType
        # Channel_name: SimCameraImageTopicOnWebviz	
        # MsgType: xpilot::msg::camera_service::CameraImage
        insert_query = f"""
        INSERT INTO DCPSChannelMsgType (Channel_name, MsgType) VALUES (?, ?);
        """
        self.cursor.execute(insert_query, (
            "SimCameraImageTopicOnWebviz", 
            "xpilot::msg::camera_service::CameraImage"
        ))
        self.conn.commit()

    def close(self):
        self.cursor.close()
        self.conn.close()


class CameraImageSqlLiteReader:
    def __init__(self, dat_path, table_suffix):
        self.dat_path = dat_path
        self.conn = sqlite3.connect(self.dat_path)
        self.cursor = self.conn.cursor()
        self.table_suffix = table_suffix
        self.table_names = f"SimCameraImageTopicOnWebviz@{self.table_suffix}"

    def fetch_rows_from_cam_image_table(self):
        query = f"SELECT * FROM '{self.table_names}';"
        self.cursor.execute(query)
        rows = self.cursor.fetchall()
        return rows

    def create_table_if_not_exists(self):
        # attributes:
        # SampleInfo_reception_timestamp INT
        # SampleInfo_source_timestamp INT
        # SampleInfo_valid_data INT
        # xpilot_cdr_sample
        # SampleInfo_source_guid INT
        # SampleInfo_base_message_timestamp INT
        # SampleInfo_cdr_sample_length INT
        # SampleInfo_publication_sequence_number INT
        # SampleInfo_reception_sequence_number INT
        # Node_Publisher_id INT
        # Sender_transmitter_id INT
        # Channel_id INT
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS '{self.table_names}' (
            SampleInfo_reception_timestamp INT,
            SampleInfo_source_timestamp INT,
            SampleInfo_valid_data INT,
            xpilot_cdr_sample,
            SampleInfo_source_guid INT,
            SampleInfo_base_message_timestamp INT,
            SampleInfo_cdr_sample_length INT,
            SampleInfo_publication_sequence_number INT,
            SampleInfo_reception_sequence_number INT,
            Node_Publisher_id INT,
            Sender_transmitter_id INT,
            Channel_id INT
        );
        """
        self.cursor.execute(create_table_query)
        self.conn.commit()

    def check_if_table_and_record_exists(self):
        query = f"SELECT COUNT(*) FROM '{self.table_names}';"
        self.cursor.execute(query)
        count = self.cursor.fetchone()[0]
        return count > 0

    def insert_data_into_cam_image_table(self, 
            reception_timestamp, 
            source_timestamp, 
            valid_data, 
            cdr_data, 
            source_guid,
            base_message_timestamp,
            cdr_length, 
            publication_seq_num,
            reception_seq_num,
            publisher_id,
            transmitter_id,
            channel_id    
        ):
        insert_query = f"""
        INSERT INTO '{self.table_names}' (
            SampleInfo_reception_timestamp,
            SampleInfo_source_timestamp,
            SampleInfo_valid_data,
            xpilot_cdr_sample,
            SampleInfo_source_guid,
            SampleInfo_base_message_timestamp,
            SampleInfo_cdr_sample_length,
            SampleInfo_publication_sequence_number,
            SampleInfo_reception_sequence_number,
            Node_Publisher_id,
            Sender_transmitter_id,
            Channel_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """

        self.cursor.execute(insert_query, (
            reception_timestamp,
            source_timestamp,
            valid_data,
            cdr_data,                       
            source_guid,
            base_message_timestamp,
            cdr_length,
            publication_seq_num,
            reception_seq_num,
            publisher_id,
            transmitter_id,
            channel_id
        ))
        self.conn.commit()

    def update_data_in_cam_image_table(self, seq_num, new_data, length):
        start_time = time.time()
        query = f"UPDATE '{self.table_names}' SET xpilot_cdr_sample = ?, SampleInfo_cdr_sample_length = ? WHERE SampleInfo_publication_sequence_number = ?;"
        self.cursor.execute(query, (new_data, length, seq_num))
        self.conn.commit()
        end_time = time.time()
        logging.info(f"Updated cam image sql for seq_num {seq_num} in {end_time - start_time:.4f} seconds")

    def close(self):
        self.cursor.close()
        self.conn.close()

class CameraVideoSqlLiteReader:
    def __init__(self, dat_path):
        self.dat_path = dat_path
        self.conn = sqlite3.connect(self.dat_path)
        self.cursor = self.conn.cursor()
        self.table_name = self.get_camera_video_table_name()
        self.table_suffix = self.get_table_suffix()

    def get_camera_video_table_name(self):
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = self.cursor.fetchall()
        for table in tables:
            if table[0].startswith("CameraVideoTopic"):
                return table[0]
        return None
    
    def get_table_suffix(self):
        if self.table_name and "@" in self.table_name:
            return self.table_name.split("@")[-1]
        return None
    
    def get_all_table_names(self):
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = self.cursor.fetchall()
        return [table[0] for table in tables]
    
    def fetch_rows_from_cam_video_table(self):
        query = f"SELECT * FROM '{self.table_name}';"
        self.cursor.execute(query)
        rows = self.cursor.fetchall()
        return rows

    def update_data_in_cam_video_table(self, seq_num, new_data, length):
        start_time = time.time()
        query = f"UPDATE '{self.table_name}' SET xpilot_cdr_sample = ?, SampleInfo_cdr_sample_length = ? WHERE SampleInfo_publication_sequence_number = ?;"
        self.cursor.execute(query, (new_data, length, seq_num))
        self.conn.commit()
        end_time = time.time()
        logging.info(f"Updated cam video sql for seq_num {seq_num} in {end_time - start_time:.4f} seconds")

    def close(self):
        self.cursor.close()
        self.conn.close()

sycned_camera_timestamp_dict_ = {
    "cam0": [],
    "cam2": [],
    "cam3": [],
    "cam4": [],
    "cam5": [],
    "cam6": [],
    "cam7": []
}

camera_ts_window = {}

def sync_all_camera_video_timestamp_cnt(cam_video_sql_reader: CameraVideoSqlLiteReader):
    synced_frame_cnt = 0
    camera_time_windows_interval_threshold = 20000000 # 20ms
    windows_min_ts = float('inf')
    # 250003712

    rows = cam_video_sql_reader.fetch_rows_from_cam_video_table()

    for row in rows:
        cdr_data = row[3]
        camera_msg = CameraVideo(cdr_data)
        ts = camera_msg.get_time_stamp().get_nsec()
        sensor_id = camera_msg.get_camera_id()
        camera_id = sensor_2_cam_type.get(int(sensor_id), -1)
        if camera_id == -1 or camera_id not in CAMERA_CONFIG:
            continue
        
        # std::numeric_limits<int64_t>::max()

        if len(camera_ts_window) == len(sycned_camera_timestamp_dict_.keys()):
            camera_ts_window.clear()
            windows_min_ts = ts
            synced_frame_cnt += 2 # need to be even
        
        windows_min_ts = min(windows_min_ts, ts)
        if synced_frame_cnt == 0: 
            logging.info(f"[At 0 Frame] ts: {ts}, windows_min_ts: {windows_min_ts}, ts - windows_min_ts: {ts - windows_min_ts} for cam{camera_id}, threshold: {camera_time_windows_interval_threshold}")
        
        if ts - windows_min_ts > camera_time_windows_interval_threshold:
            camera_ts_window.clear()
            windows_min_ts = ts
            synced_frame_cnt += 2 # need to be even
        
        camera_ts_window[camera_id] = ts
        sycned_camera_timestamp_dict_[f"cam{camera_id}"].append(synced_frame_cnt)

        if synced_frame_cnt == 0:
            logging.info(f"[At 0 Frame] Initial synced frame count at ts: {ts} for cam{camera_id}")

    # print the synced frame count for each camera
    for cam_key, ts_list in sycned_camera_timestamp_dict_.items():
        logging.info(f"{cam_key} synced frame count: {ts_list}")


def encode_single_frame_to_hevc(
    frame_bgr,
    width,
    height,
    fps=12,
    frame_type=3,  # 默认为 IDR_FRAME
    bitrate_kbps=80737
):
    """
    根据 frame_type 编码单帧为 HEVC Annex B 流。
    
    Args:
        frame_type (int): 
            0 -> VFT_P_FRAME
            1 -> VFT_B_FRAME (fallback to P)
            2 -> VFT_I_FRAME (treated as IDR for HEVC)
            3 -> VFT_IDR_FRAME
    """
    if not frame_bgr.flags['C_CONTIGUOUS']:
        frame_bgr = np.ascontiguousarray(frame_bgr)

    # 默认参数
    gop = "1000"               # 足够大，确保非关键帧
    x265_params = "repeat-headers=0:keyint=1000:min-keyint=1000"
    bf = "0"                   # 禁用 B 帧（匹配线上）

    if frame_type == 3:  # VFT_IDR_FRAME
        gop = "1"
        x265_params = "repeat-headers=1:keyint=1:min-keyint=1"
    elif frame_type == 2:  # VFT_I_FRAME → treat as IDR (HEVC has no non-IDR I-frames in practice)
        gop = "1"
        x265_params = "repeat-headers=1:keyint=1:min-keyint=1"
    elif frame_type in (0, 1):  # VFT_P_FRAME or VFT_B_FRAME → P-frame
        gop = "1000"
        x265_params = "repeat-headers=0:keyint=1000:min-keyint=1000"
        if frame_type == 1:
            # 如果未来要支持 B 帧，可设 bf="2"
            bf = "0"  # 保持 bf=0

    cmd = [
        'ffmpeg',
        '-y',
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-s', f'{width}x{height}',
        '-pix_fmt', 'bgr24',
        '-r', str(fps),
        '-i', '-',
        '-vf', 'format=yuv420p',
        '-c:v', 'libx265',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-b:v', f'{bitrate_kbps}k',
        '-maxrate', f'{bitrate_kbps}k',
        '-bufsize', f'{bitrate_kbps}k',
        '-g', gop,
        '-bf', bf,
        '-x265-params', x265_params,
        '-bsf:v', 'hevc_mp4toannexb',
        '-frames:v', '1',
        '-f', 'hevc',
        '-'
    ]

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = process.communicate(input=frame_bgr.tobytes())

    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {stderr.decode()}")

    return stdout

def insert_all_cam_init_records(
        cam_video_sql_reader: CameraVideoSqlLiteReader,
        cam_image_sql_reader: CameraImageSqlLiteReader,
    ):
    cam_image_sql_reader.create_table_if_not_exists()
    all_allow_cam_ids = list(CAMERA_CONFIG.keys())
    rows = cam_video_sql_reader.fetch_rows_from_cam_video_table()
    write_image_frame_set_dict = dict()

    is_table_empty = not cam_image_sql_reader.check_if_table_and_record_exists()
    if not is_table_empty:
        logging.info("CameraImage table already has records.")

    for row in rows:
        cdr_data = row[3]
        camera_msg = CameraVideo(cdr_data)
        sensor_id = camera_msg.get_camera_id()
        camera_id = sensor_2_cam_type.get(int(sensor_id), -1)
        if camera_id == -1 or camera_id not in all_allow_cam_ids:
            continue

        timestamp = camera_msg.get_time_stamp().get_nsec()
        origin_fps = CAMERA_CONFIG[camera_id]["fps"]
        image_fps = CAMERA_CONFIG[camera_id]["img_fps"]

        # 根据fps，判断当前帧是否需要写入图片，将需要写图的时间戳保存起来
        if camera_id not in write_image_frame_set_dict:
            write_image_frame_set_dict[camera_id] = set()
        if (timestamp % (origin_fps // image_fps) == 0):
            write_image_frame_set_dict[camera_id].add(timestamp)

            if is_table_empty:
                logging.info(f"Inserting Camera ID: {camera_id}, Timestamp: {timestamp} into CameraImage table.")
                cam_image_sql_reader.insert_data_into_cam_image_table(
                        reception_timestamp=row[0],
                        source_timestamp=row[1],
                        valid_data=row[2],
                        cdr_data=None,
                        source_guid=row[4],
                        base_message_timestamp=row[5],
                        cdr_length=-1,
                        publication_seq_num=row[7],
                        reception_seq_num=row[8],
                        publisher_id=row[9],
                        transmitter_id=row[10],
                        channel_id=row[11]
                    )
            else:
                pass
    
    return write_image_frame_set_dict

def align_frame_count_to_topic(
    cam_video_sql_reader: CameraVideoSqlLiteReader,
    cam_id,
):
    rows = cam_video_sql_reader.fetch_rows_from_cam_video_table()
    curr_frame_idx = 1
    for row in rows:
        publication_seq_num = row[7]
        cdr_data = row[3]
        camera_msg = CameraVideo(cdr_data)
        sensor_id = camera_msg.get_camera_id()
        camera_id = sensor_2_cam_type.get(int(sensor_id), -1)
        meta = camera_msg.get_metadata()  # bytes
        if camera_id == -1 or camera_id != cam_id:
            continue
        timestamp = camera_msg.get_time_stamp().get_nsec()
        new_frame_cnt = sycned_camera_timestamp_dict_[f"cam{cam_id}"][curr_frame_idx - 1]
        new_meta  = (meta[:16] + list(new_frame_cnt.to_bytes(4, 'little')) + meta[20:])
        camera_msg.set_metadata(new_meta)
        new_cdr_data = camera_msg.SerializeToString()
        length = len(new_cdr_data)
        logging.info(f"[Frame Count Align] ts: {timestamp} Updating Camera Video SQL for camID: {cam_id}, new_frame_cnt: {new_frame_cnt}, frame type: {camera_msg.get_frame_type()}, Seq Num: {publication_seq_num}, New Frame Count: {new_frame_cnt}, New Data Length: {length}")
        cam_video_sql_reader.update_data_in_cam_video_table(publication_seq_num, new_cdr_data, length)

        curr_frame_idx += 1

    logging.info(f"Finished aligning frame count for camera ID: {cam_id}")

def match_local_camera_to_topic(
        cam_video_sql_reader: CameraVideoSqlLiteReader, 
        cam_image_sql_reader: CameraImageSqlLiteReader,
        cam_id, 
        image_base_dir, 
        write_image_frame_set_dict,
        to_update_dat=False
    ):
    rows = cam_video_sql_reader.fetch_rows_from_cam_video_table()

    target_cam_frame_cnt = 0
    for row in rows:
        cdr_data = row[3]
        camera_msg = CameraVideo(cdr_data)
        sensor_id = camera_msg.get_camera_id()
        camera_id = sensor_2_cam_type.get(int(sensor_id), -1)
        if camera_id == -1 or camera_id != cam_id:
            continue
        target_cam_frame_cnt += 1

    curr_frame_idx = 1
    curr_img_frame_idx = 1
    for row in rows:
        publication_seq_num = row[7]
        cdr_data = row[3]
        camera_msg = CameraVideo(cdr_data)
        sensor_id = camera_msg.get_camera_id()
        camera_id = sensor_2_cam_type.get(int(sensor_id), -1)
        meta = camera_msg.get_metadata()  # bytes
        if camera_id == -1 or camera_id != cam_id:
            continue
        timestamp = camera_msg.get_time_stamp().get_nsec()
        closest_timestamp = find_closest_timestamp(all_timestamps_in_cam.get(cam_id, []), timestamp)
        logging.info(f"Camera ID: {cam_id}, Message Timestamp: {timestamp}, Closest Timestamp: {closest_timestamp}")

        img = get_timestamp_image_from_local(cam_id, closest_timestamp, image_base_dir)
        if img is None:
            logging.info(f"No matching image found for Camera ID: {cam_id} at timestamp: {closest_timestamp}")
            continue

        height, width, _ = img.shape
        # enum VideoFrameType {
        #     VFT_P_FRAME   = 0,
        #     VFT_B_FRAME   = 1,
        #     VFT_I_FRAME   = 2,
        #     VFT_IDR_FRAME = 3
        # };
        hevc_data = encode_single_frame_to_hevc(
            img, 
            width, 
            height, 
            fps=CAMERA_CONFIG[cam_id]["fps"], 
            frame_type=int(camera_msg.get_frame_type()),
            bitrate_kbps=CAMERA_CONFIG[cam_id]["bitrate_kbps"]
        )
        logging.info(f"Frames: {curr_frame_idx}/{target_cam_frame_cnt} Encoded HEVC data length: {len(hevc_data)} for Camera ID: {cam_id} at timestamp: {closest_timestamp}")
        flatted_img = None
        image_frame_idx = -1
        if cam_id in write_image_frame_set_dict and timestamp in write_image_frame_set_dict[cam_id]:
            flatted_img = convert_and_flatten_image_data(img, cam_id)
            image_frame_idx = curr_img_frame_idx
            curr_img_frame_idx += 1
        
        logging.info(f"Image Frame Index: {image_frame_idx}, Flattened Image Data Length: {len(flatted_img) if flatted_img is not None else 'N/A'}")

        if to_update_dat:
            new_frame_cnt = sycned_camera_timestamp_dict_[f"cam{cam_id}"][curr_frame_idx - 1]
            new_meta  = (meta[:16] + list(new_frame_cnt.to_bytes(4, 'little')) + meta[20:])
            camera_msg.set_metadata(new_meta)
            camera_msg.set_data(list(hevc_data))
            new_cdr_data = camera_msg.SerializeToString()
            length = len(new_cdr_data)
            logging.info(f"Updating Camera Video SQL for cam ID: {cam_id}, new_frame_cnt: {new_frame_cnt}, frame type: {camera_msg.get_frame_type()}, Seq Num: {publication_seq_num}, New Frame Count: {new_frame_cnt}, New Data Length: {length}")
            cam_video_sql_reader.update_data_in_cam_video_table(publication_seq_num, new_cdr_data, length)
            
            if flatted_img is not None:
                camera_img_msg = CameraImage()
                camera_img_msg.set_camera_id(sensor_id)
                camera_img_msg.set_time_stamp(camera_msg.get_time_stamp())
                camera_img_msg.set_format(np.int32(3))
                camera_img_msg.set_width(np.uint16(CAMERA_CONFIG[cam_id]["image_width"]))
                camera_img_msg.set_height(np.uint16(CAMERA_CONFIG[cam_id]["image_height"]))
                camera_img_msg.set_size(np.uint32(len(flatted_img)))
                camera_img_msg.set_offset(np.uint16(0))
                camera_img_msg.set_data(flatted_img)
                new_img_cdr_data = camera_img_msg.SerializeToString()
                length = len(new_img_cdr_data)
                cam_image_sql_reader.update_data_in_cam_image_table(
                    publication_seq_num, 
                    new_img_cdr_data, 
                    length
                )
        
        curr_frame_idx += 1

    logging.info(f"Finished matching local camera images to topic for camera ID: {cam_id}")

def convert_and_flatten_image_data(image_data, cam_id):
    # image_data is likely (H, W, 3) from OpenCV
    if image_data.ndim == 3:
        h, w, c = image_data.shape
    elif image_data.ndim == 2:
        h, w = image_data.shape
        c = 1
    else:
        raise ValueError("Unexpected image dimension")

    target_w = CAMERA_CONFIG[cam_id]["image_width"]
    target_h = CAMERA_CONFIG[cam_id]["image_height"]

    # Resize if needed
    if (h, w) != (target_h, target_w):
        image_data = cv2.resize(image_data, (target_w, target_h), interpolation=cv2.INTER_AREA)

    # 如果原始 data 是 RGB（而 OpenCV 是 BGR），先转换颜色空间（关键！）
    img_rgb = cv2.cvtColor(image_data, cv2.COLOR_BGR2RGB)

    # Flatten to 1D array (H*W*3,)
    flat_array = img_rgb.flatten()

    # 转成 list，每个元素显式为 np.uint8（保持类型一致）
    data_like = [np.uint8(x) for x in flat_array]
    return data_like

def get_timestamp_image_from_local(cam_id, target_timestamp, image_base_dir):
    cam_name = f"cam{cam_id}"
    image_path = os.path.join(image_base_dir, cam_name, f"{target_timestamp}.png")
    if os.path.exists(image_path):
        img = cv2.imread(image_path, cv2.IMREAD_COLOR)
        return img

    return None

def select_from_camera_image_topic(cam_image_sql_reader, cam_id, output_dir):
    image_cam_info_dict = {
        cam_id: []
    }
    rows = cam_image_sql_reader.fetch_rows_from_cam_image_table()
    for row in rows:
        cdr_data = row[3]
        camera_msg = CameraImage(cdr_data)
        sensor_id = camera_msg.get_camera_id()
        camera_id = sensor_2_cam_type.get(int(sensor_id), -1)
        if camera_id == -1 or camera_id != cam_id:
            continue

        logging.info(f"Timestamp: {camera_msg.get_time_stamp().get_nsec()}, "
                f"camera type: {camera_id}, Image format: {camera_msg.get_format()}, "
                f"shape: {camera_msg.get_width()}x{camera_msg.get_height()}, "
                f"data length: {camera_msg.get_size()}, offset: {camera_msg.get_offset()}, "
                f"data len: {len(camera_msg.get_data())}, data type: {type(camera_msg.get_data())}, "
                f"data sample: {camera_msg.get_data()[:10]}")

        image_cam_info_dict[camera_id].append({
            "timestamp": camera_msg.get_time_stamp().get_nsec(),
            # "image_codec": camera_msg.get_format(), # CIC_JPEG
            "width": camera_msg.get_width(),
            "height": camera_msg.get_height(),
            # "data_length": camera_msg.get_size(),
            "data": camera_msg.get_data()
        })

    for camera_id, info_list in image_cam_info_dict.items():
        if camera_id != cam_id:
            continue
        fps = get_fps(image_cam_info_dict, camera_id)
        logging.info(f"Camera Type: {camera_id}, Total Images: {len(info_list)}, FPS: {fps}")
        dump_cam_images_jpeg(image_cam_info_dict, camera_id, output_dir)

    # release resources
    image_cam_info_dict[camera_id] = []

def dump_cam_images_jpeg(image_cam_info_dict, camera_type, output_dir, color_format='RGB'):
    if camera_type not in image_cam_info_dict:
        logging.info(f"No data found for camera type: {camera_type}")
        return
    
    if not image_cam_info_dict[camera_type] or len(image_cam_info_dict[camera_type]) == 0:
        logging.info(f"No images to dump for camera type: {camera_type}")
        return

    os.makedirs(output_dir, exist_ok=True)
    image_dir = os.path.join(output_dir, f"camera_{camera_type}_images")
    os.makedirs(image_dir, exist_ok=True)

    for idx, frame in enumerate(image_cam_info_dict[camera_type]):
        width = frame["width"]
        height = frame["height"]

        data = frame["data"]  # This is list[np.uint8] of flattened pixels
        if not data:
            logging.info(f"Empty data for frame {idx}, skipping.")
            continue

        # Convert to numpy array
        arr = np.array(data, dtype=np.uint8)

        # Reshape based on expected image shape
        if color_format == 'RGB':
            img = arr.reshape((height, width, 3))
            img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        elif color_format == 'BGR':
            img_bgr = arr.reshape((height, width, 3))
        elif color_format == 'GRAY':
            img_bgr = arr.reshape((height, width))  # Grayscale
        else:
            raise ValueError("Unsupported color format")

        # Encode to JPEG
        success, encoded = cv2.imencode('.jpg', img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not success:
            logging.info(f"Failed to encode frame {idx}")
            continue

        image_path = os.path.join(image_dir, f"frame_{idx:06d}.jpg")
        with open(image_path, 'wb') as f:
            f.write(encoded.tobytes())

    logging.info(f"JPEG images dumped to: {image_dir} (Total images: {len(image_cam_info_dict[camera_type])})")

def select_from_camera_video_topic(
        cam_video_sql_reader, 
        cam_id, 
        output_dir, 
        dat_base_id=""
    ):
    cam_info_dict = {}
    rows = cam_video_sql_reader.fetch_rows_from_cam_video_table()
    for row in rows:
        cdr_data = row[3]
        camera_msg = CameraVideo(cdr_data)
        sensor_id = camera_msg.get_camera_id()
        camera_id = sensor_2_cam_type.get(int(sensor_id), -1)
        if camera_id == -1 or camera_id != cam_id:
            continue

        logging.info(f"Timestamp: {camera_msg.get_time_stamp().get_nsec()}, "
                f"camera type: {camera_id}, Frame Type: {camera_msg.get_frame_type()}, "
                f"Video codec: {camera_msg.get_video_codec()}, shape: {camera_msg.get_width()}x{camera_msg.get_height()}, "
                f"data length: {camera_msg.get_size()}, meta_data frame_cnt: {int.from_bytes(camera_msg.get_metadata()[16:20], 'little')}, ")
        if camera_id not in cam_info_dict:
            cam_info_dict[camera_id] = list()
        cam_info_dict[camera_id].append({
            "timestamp": camera_msg.get_time_stamp().get_nsec(),
            "frame_type": camera_msg.get_frame_type(),
            "video_codec": camera_msg.get_video_codec(), # VCT_HEVC
            "width": camera_msg.get_width(),
            "height": camera_msg.get_height(),
            "data_length": camera_msg.get_size(),
            "data": camera_msg.get_data()
        })

    for camera_id, info_list in cam_info_dict.items():
        if camera_id != cam_id:
            continue

        fps = get_fps(cam_info_dict, camera_id)
        logging.info(f"Camera Type: {camera_id}, Total Frames: {len(info_list)}, FPS: {fps:.2f}")
        dump_cam_video_hevc(cam_info_dict, camera_id, output_dir, dat_base_id=dat_base_id)

        # release resources
    cam_info_dict[camera_id] = []

def get_fps(cam_info_dict, camera_id):
    if camera_id not in cam_info_dict:
        return 0
    timestamps = [frame["timestamp"] for frame in cam_info_dict[camera_id]]
    if len(timestamps) < 2:
        return 0
    time_diffs = [t2 - t1 for t1, t2 in zip(timestamps[:-1], timestamps[1:])]
    avg_time_diff = sum(time_diffs) / len(time_diffs)  # in nanoseconds
    fps = 1e9 / avg_time_diff if avg_time_diff > 0 else 0
    return fps

def dump_cam_video_hevc(cam_info_dict, camera_type, output_dir, dat_base_id=""):
    if camera_type not in cam_info_dict:
        logging.info(f"No data found for camera type: {camera_type}")
        return
    
    if not cam_info_dict[camera_type] or len(cam_info_dict[camera_type]) == 0:
        logging.info(f"No frames to dump for camera type: {camera_type}")
        return

    os.makedirs(output_dir, exist_ok=True)
    hevc_file_path = os.path.join(output_dir, f"camera_{camera_type}_video_{dat_base_id}.hevc")

    # 按时间戳排序（确保帧顺序正确）
    # frames = sorted(cam_info_dict[camera_type], key=lambda x: x["timestamp"])

    with open(hevc_file_path, 'wb') as f:
        for frame in cam_info_dict[camera_type]:
            data = frame["data"]
            if isinstance(data, bytes):
                f.write(data)
            else:
                # 如果 data 是 bytearray 或 memoryview，也转为 bytes
                f.write(bytes(data))
    
    logging.info(f"HEVC video dumped to: {hevc_file_path} (Total frames: {len(cam_info_dict[camera_type])})")

    # convert to mp4 for easy playback
    cmd = [
        'ffmpeg',
        '-y',
        '-i', hevc_file_path,
        '-c:v', 'copy',
        os.path.join(output_dir, f"camera_{camera_type}_video_{dat_base_id}.mp4")
    ]
    subprocess.run(cmd, check=True)
    logging.info(f"Converted HEVC to MP4 for camera {camera_type}")

def read_local_image_to_encode(image_base_dir, cam_id, output_dir, to_encode=True):
    cam_name = f"cam{cam_id}"
    image_dir = os.path.join(image_base_dir, cam_name)
    image_files = sorted([f for f in os.listdir(image_dir) if f.endswith(('.png', '.jpg', '.jpeg'))])
    frames = []
    for img_file in image_files:
        img_path = os.path.join(image_dir, img_file)
        img = cv2.imread(img_path, cv2.IMREAD_COLOR)
        if img is not None:
            frames.append(img)
    
    if not frames:
        logging.info(f"No images found in directory: {image_dir}")
        return [], 0, 0

    height, width, _ = frames[0].shape
    logging.info(f"Read {len(frames)} images for camera {cam_id}, resolution: {width}x{height}")

    # 编码
    idx = 0
    encoded_frames = []
    for img in frames:
        if to_encode:
            logging.info(f"Encoding frame {idx+1}/{len(frames)} for camera {cam_id}, file: {image_files[idx]}")
            hevc_data = encode_single_frame_to_hevc(img, width, height, fps=30)
            idx += 1

            # 推断帧类型（含 SPS/PPS 的通常是 I 帧）
            if b'\x44\x01' in hevc_data[:20]:  # HEVC SPS NAL unit header
                frame_type = 0  # I-frame
            else:
                frame_type = 1  # P-frame
            
            encoded_frames.append({
                "data": hevc_data,  
                "frame_type": frame_type,
                "width": width,
                "height": height,
                "data_length": len(hevc_data)
            })
        else:
            logging.info(f"Skipping encoding for frame {idx+1}/{len(frames)} for camera {cam_id}, file: {image_files[idx]}")
            img_data_bytes = img.flatten().tobytes()
            encoded_frames.append({
                "data": img_data_bytes,
                "frame_type": 2,  # Raw frame
                "width": width,
                "height": height,
                "data_length": len(img_data_bytes)
            })
            idx += 1

    cam_info_dict = {cam_id: []}
    for i, frame in enumerate(encoded_frames):
        cam_info_dict[cam_id].append({
            "timestamp": int(i * (1e9 / 30)),  # 30fps
            "frame_type": frame["frame_type"],
            "video_codec": "VCT_HEVC",
            "width": frame["width"],
            "height": frame["height"],
            "data_length": frame["data_length"],
            "data": frame["data"]
        })

    # 直接调用你已有的函数
    dump_cam_video_hevc(cam_info_dict, camera_type=cam_id, output_dir=output_dir)

    return encoded_frames, width, height

def find_closest_timestamp(timestamps, target_timestamp):
    """在已排序的 timestamps 列表中，找到最接近 target_timestamp 的值"""
    if not timestamps:
        return None
    closest = min(timestamps, key=lambda x: abs(x - target_timestamp))
    return closest

def read_local_image_to_timestamp(image_base_dir, cam_id):
    cam_name = f"cam{cam_id}"
    image_dir = os.path.join(image_base_dir, cam_name)
    image_files = sorted([f for f in os.listdir(image_dir) if f.endswith(('.png', '.jpg', '.jpeg'))])
    timestamps = []
    for img_file in image_files:
        # 假设文件名格式为 <timestamp>.png
        base_name = os.path.splitext(img_file)[0]
        try:
            timestamp = int(base_name)
            timestamps.append(timestamp)
        except ValueError:
            logging.info(f"Invalid filename (not a timestamp): {img_file}")
            continue
    
    logging.info(f"Read {len(timestamps)} timestamps for camera {cam_id} from directory: {image_dir}")

    all_timestamps_in_cam[cam_id] = timestamps

def get_dat_base_name(dat_path):
    dat_base_path = os.path.basename(dat_path)
    # recording_0_25-06-06_16:18:27.dat -> recording_0_25-06-06_16-18-27
    dat_base_name = os.path.splitext(dat_base_path)[0]
    dat_base_name = dat_base_name.replace(":", "-")
    return dat_base_name

def process_one_dds(dat_path, base_dir, mode, discovery_file_path=""):
    try: 
        dat_base_id = get_dat_base_name(dat_path)
        # /workspace/wangyl11@xiaopeng.com/aeb_scenario_edit/Scenario_2025-11-27_01-39-14/origin_dds_dat_files
        # dat_path = os.path.join(base_dir, "origin_dds_dat_files", dat_file_name)
        cam_video_sql_reader = CameraVideoSqlLiteReader(dat_path)
        table_suffix = cam_video_sql_reader.table_suffix
        cam_image_sql_reader = CameraImageSqlLiteReader(dat_path, table_suffix)

        discovery_sql_reader = None
        if discovery_file_path and os.path.exists(discovery_file_path):
            discovery_sql_reader = DiscoverySqlLiteReader(discovery_file_path)

        # cam_list = [3, 4, 5, 6, 7]
        cam_list = [0, 2, 3, 4, 5, 6, 7]
        # aeb_scenario_edit/Scenario_2025-11-27_01-39-14/simulator_render/redistort_rgb_harmonized
        image_base_dir = os.path.join(base_dir, "simulator_render", "redistort_rgb_harmonized")
        hevc_output_dir = os.path.join(base_dir, "simulator_render", "hevc_videos")
        image_output_dir = os.path.join(base_dir, "simulator_render", "image_videos")
        origin_output_dir = os.path.join(base_dir, "simulator_render", "origin_hevc_videos")

        write_image_frame_set_dict = dict()
        if mode == "encode":
            write_image_frame_set_dict = insert_all_cam_init_records(
                cam_video_sql_reader,
                cam_image_sql_reader
            )

        if mode == "encode" or mode == "fm_origin":
            sync_all_camera_video_timestamp_cnt(cam_video_sql_reader)

        for cam_id in cam_list:
            if mode == "origin":
                # dump existing hevc from dat file
                cam_origin_output_dir = os.path.join(origin_output_dir, f"camera_{cam_id}")
                select_from_camera_video_topic(cam_video_sql_reader, cam_id, cam_origin_output_dir)

            if mode == "encode":
                # generate all timestamps from local images
                read_local_image_to_timestamp(
                    image_base_dir,
                    cam_id
                )

                cam_hevc_output_dir = os.path.join(hevc_output_dir, f"camera_{cam_id}")
                to_dump_hevc = True
                match_local_camera_to_topic(
                    cam_video_sql_reader, 
                    cam_image_sql_reader,
                    cam_id,
                    image_base_dir,
                    write_image_frame_set_dict=write_image_frame_set_dict,
                    to_update_dat=True
                )

                if discovery_sql_reader:
                    discovery_sql_reader.insert_sim_camera_image_topic_table()

                if to_dump_hevc:
                    cam_hevc_output_dir = os.path.join(hevc_output_dir, f"cam{cam_id}")
                    select_from_camera_video_topic(cam_video_sql_reader, cam_id, cam_hevc_output_dir, dat_base_id=dat_base_id)

            if mode == "fm_origin":
                # align frame count to topic
                align_frame_count_to_topic(
                    cam_video_sql_reader,
                    cam_id,
                )

            if mode == "img_test":
                # test select from camera image topic
                select_from_camera_image_topic(cam_image_sql_reader, cam_id, image_output_dir)
    finally:
        cam_video_sql_reader.close()
        cam_image_sql_reader.close()
        if discovery_sql_reader:
            discovery_sql_reader.close()

# MODE ENUM
MODE_ENUM = {
    "origin": "origin",
    "encode": "encode",
    "img_test": "img_test",
    "fm_origin": "fm_origin",
}

def get_all_dat_in_dir(dat_dir):
    dat_files = []
    for file_name in os.listdir(dat_dir):
        if file_name.endswith('.dat'):
            dat_files.append(file_name)
    return dat_files

def check_and_download_from_scenario(dat_dir, scenario_id):
    # Placeholder for checking and downloading from scenario
    _, scenario_config, cloud_bucket, _ = scenario_info_update.query_scenario_by_id(scenario_id)
    if scenario_config is None:
        logging.info(f"[check_and_download_from_scenario] Scenario ID {scenario_id} not found.")
        return
    
    if not os.path.exists(dat_dir):
        os.makedirs(dat_dir, exist_ok=True)

    # Download files from cloud bucket
    # "ddsDataSource": {
    #     "dds_files": [
    #       "demo/aeb_test_dds/Scenario_2025-11-28_05-50-32/recording_0_25-09-21_14:12:06.dat"
    #     ],
    #     "metadata": "cloudsim_scenario/driving/37/2025-11-28/30240154/unknown-L1NNSGHC6PB009513-h93xlidc-233632278929703962_2025-09-21-06-12-33/metadata",
    #     "calibration": "cloudsim_scenario/driving/37/2025-11-28/30240154/unknown-L1NNSGHC6PB009513-h93xlidc-233632278929703962_2025-09-21-06-12-33/calibration",
    #     "discovery": "demo/aeb_test_dds/Scenario_2025-11-28_05-50-32/discovery"
    #   },
    dds_data_source = scenario_config.get("ddsDataSource", {})
    dds_files = dds_data_source.get("dds_files", [])
    metadata_file = dds_data_source.get("metadata", "")
    calibration_dir = dds_data_source.get("calibration", "")
    discovery_file = dds_data_source.get("discovery", "")

    for dds_file in dds_files:
        dds_downloader.download_file_from_oss(cloud_bucket, dds_file, dat_dir)

    if metadata_file:
        dds_downloader.download_file_from_oss(cloud_bucket, metadata_file, dat_dir)
    
    if calibration_dir:
        dds_downloader.download_file_from_oss(cloud_bucket, calibration_dir, dat_dir)

    if discovery_file:
        dds_downloader.download_file_from_oss(cloud_bucket, discovery_file, dat_dir)

def upload_all_dat_to_oss(dat_dir, upload_dds_oss_dir, scenario_id):
    _, _, oss_bucket, _ = scenario_info_update.query_scenario_by_id(scenario_id)
    
    # upload all file and dir in dat_dir to upload_dds_oss_dir
    for item in os.listdir(dat_dir):
        local_path = os.path.join(dat_dir, item)
        oss_path = os.path.join(upload_dds_oss_dir, item)
        logging.info(f"[upload_all_dat_to_oss] Uploading {local_path} to OSS at {oss_path}")
        dds_downloader.upload_object_to_oss(oss_bucket, local_path, oss_path)

def parse_args():
    parser = argparse.ArgumentParser(description="Camera Video Processing")
    parser.add_argument('--dat_dir', type=str, required=True, help='Path to the .dat dir')
    parser.add_argument('--base_dir', type=str, required=True, help='Base directory for images and outputs')
    parser.add_argument('--mode', type=str, choices=MODE_ENUM.keys(), required=True, help='Operation mode: origin, encode, img_test')
    parser.add_argument('--scenario_id', type=str, required=True, help='Scenario ID (optional)')
    parser.add_argument('--edited_3dgs_version', type=str, required=True, help='Edited 3DGS version (optional)')
    parser.add_argument('--upload_dds_oss_dir', type=str, required=True, help='Upload DDS OSS directory (optional)')
    return parser.parse_args()

if __name__ == "__main__":
    # base_path = "/home/wangyl11/Downloads/dds/aeb_scenario_edit/20251118_2010_harmony_4"
    # dat_file_name = "recording_0_25-07-17_12:43:33.dat"
    # mode = MODE_ENUM["encode"]  # "origin" or "encode" or "fm_origin"
    args = parse_args()
    base_path = args.base_dir
    dat_dir_name = args.dat_dir
    scenario_id = args.scenario_id
    upload_dds_oss_dir = args.upload_dds_oss_dir
    edited_3dgs_version = args.edited_3dgs_version

    check_and_download_from_scenario(dat_dir_name, scenario_id)

    mode = MODE_ENUM[args.mode]
    dat_file_names = get_all_dat_in_dir(dat_dir_name)

    discovery_file_path = os.path.join(dat_dir_name, "discovery")

    for dat_file_name in dat_file_names:
        logging.info(f"dat_file_name: {dat_file_name}， base_path: {base_path}, mode: {mode}")
        dat_abs_file_path = os.path.join(dat_dir_name, dat_file_name)
        process_one_dds(
            dat_abs_file_path, 
            base_path, 
            mode=mode, 
            discovery_file_path=discovery_file_path
        )
    
    upload_all_dat_to_oss(dat_dir_name, upload_dds_oss_dir, scenario_id)
    scenario_info_update.update_scenario_info(scenario_id, edited_3dgs_version, upload_dds_oss_dir)
