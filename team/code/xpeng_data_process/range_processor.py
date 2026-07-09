import json
import math
import os
import matplotlib.pyplot as plt
from utils.annotation_sf import convert_obj_to_rig


class RangeProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.object_bbox_src = str(self.cfg.processor.object_bbox_src).lower()
        (
            self.sxnet_topic,
            self.object_bbox_topic,
            self.mflp_topic,
        ) = self.load_jsons(self.cfg.clip_path, self.object_bbox_src)
        self.parse_json_gen_lane_change_range(
            self.sxnet_topic,
            self.object_bbox_topic,
            self.mflp_topic,
            self.object_bbox_src,
            self.cfg.clip_path,
        )

    def load_jsons(self, json_dir=None, object_bbox_src="dxnet"):
        """
        从JSON文件中加载StaticXNetTopic、MfLocalPoseTopic以及配置指定的动态障碍物Topic
        
        Args:
            json_dir: JSON文件目录路径
            object_bbox_src: 动态障碍物来源，'dxnet' 或 'sf'
        
        Returns:
            tuple: (sxnet_topic, object_bbox_topic, mflp_topic)
        """
        object_bbox_src = (object_bbox_src or "dxnet").lower()
        if object_bbox_src not in {"dxnet", "sf"}:
            raise ValueError(f"Unsupported object_bbox_src: {object_bbox_src}: dxnet or sf expected")
        
        # 定义JSON文件路径
        static_xnet_json = os.path.join(json_dir, "StaticXNetTopic.json")
        dynamic_xnet_json = os.path.join(json_dir, "DynamicXNetTopic.json")
        sensor_fusion_json = os.path.join(json_dir, "SensorFusionTopic.json")
        mf_local_pose_json = os.path.join(json_dir, "MfLocalPoseTopic.json")
        print("Loading JSON...")
        
        required_files = [
            (static_xnet_json, "StaticXNetTopic.json"),
            (mf_local_pose_json, "MfLocalPoseTopic.json"),
        ]
        if object_bbox_src == "dxnet":
            required_files.append((dynamic_xnet_json, "DynamicXNetTopic.json"))
        else:
            required_files.append((sensor_fusion_json, "SensorFusionTopic.json"))
        
        # 检查文件是否存在
        for json_file, name in required_files:
            if not os.path.exists(json_file):
                raise FileNotFoundError(f"JSON no found: {name} - {json_file}")
        
        # 加载StaticXNetTopic数据
        print("Loading StaticXNetTopic...")
        sxnet_topic = {}
        try:
            with open(static_xnet_json, 'r', encoding='utf-8') as f:
                static_data = json.load(f)
            
            if isinstance(static_data, list):
                for item in static_data:
                    timestamp = item.get("time_stamp", {}).get("nsec")
                    if timestamp:
                        sxnet_topic[timestamp] = item
            else:
                # 如果是单个对象，尝试获取时间戳
                timestamp = static_data.get("time_stamp", {}).get("nsec", 0)
                sxnet_topic[timestamp] = static_data
                
            print(f"✓ Loaded {len(sxnet_topic)} StaticXNetTopic items")
        except Exception as e:
            raise Exception(f"Load StaticXNetTopic failed: {e}")
        
        # 加载动态障碍物Topic
        object_topic = {}
        if object_bbox_src == "sf":
            print("Loading SensorFusionTopic...")
            with open(sensor_fusion_json, 'r', encoding='utf-8') as f:
                sf_data = json.load(f)
            
            if isinstance(sf_data, list):
                for item in sf_data:
                    timestamp = item.get("time_stamp", {}).get("nsec")
                    if timestamp:
                        object_topic[timestamp] = item
            else:
                # 如果是单个对象，尝试获取时间戳
                timestamp = sf_data.get("time_stamp", {}).get("nsec", 0)
                object_topic[timestamp] = sf_data
                
            print(f"Loaded {len(object_topic)} SensorFusionTopic items")
        else:
            print("Loading DynamicXNetTopic...")
            with open(dynamic_xnet_json, 'r', encoding='utf-8') as f:
                dynamic_data = json.load(f)
            
            if isinstance(dynamic_data, list):
                for item in dynamic_data:
                    timestamp = item.get("time_stamp", {}).get("nsec")
                    if timestamp:
                        object_topic[timestamp] = item
            else:
                # 如果是单个对象，尝试获取时间戳
                timestamp = dynamic_data.get("time_stamp", {}).get("nsec", 0)
                object_topic[timestamp] = dynamic_data
                
            print(f"Loaded {len(object_topic)} DynamicXNetTopic items successfully")
        
        # 加载MfLocalPoseTopic数据
        print("Loading MfLocalPoseTopic...")
        mflp_topic = {}
        with open(mf_local_pose_json, 'r', encoding='utf-8') as f:
            mflp_data = json.load(f)
        
        if isinstance(mflp_data, list):
            for item in mflp_data:
                timestamp = item.get("time_stamp", {}).get("nsec")
                if timestamp:
                    mflp_topic[timestamp] = item
        else:
            # 如果是单个对象，尝试获取时间戳
            timestamp = mflp_data.get("time_stamp", {}).get("nsec", 0)
            mflp_topic[timestamp] = mflp_data
            
        print(f"✓ Loaded {len(mflp_topic)} MfLocalPoseTopic items")
        
        print("✓ All JSON Loaded!")
        object_topic_name = "DynamicXNetTopic" if object_bbox_src == "dxnet" else "SensorFusionTopic"
        print(f"  Total: {len(sxnet_topic)} StaticXNetTopic, {len(object_topic)} {object_topic_name}, {len(mflp_topic)} MfLocalPoseTopic")
        
        # 验证数据完整性
        if len(sxnet_topic) == 0:
            print("Warn: StaticXNetTopic is None")
        if len(object_topic) == 0:
            print(f"Warn: {object_topic_name} is None")
        if len(mflp_topic) == 0:
            print("Warn: MfLocalPoseTopic is None")
        
        return sxnet_topic, object_topic, mflp_topic

    def parse_json_gen_lane_change_range(self, sxnet_topic, object_topic, mflp_topic, object_bbox_src, output_path):
        nearest_left_boundary_points = []
        nearest_right_boundary_points = []
        nearset_left_dynamic_points = []
        nearset_right_dynamic_points = []
        nearest_ego_traj_points = []
        left_dis_arr = []
        right_dis_arr = []
        time_arr = []
        
        localpose_dic = self.parse_localpose_json(mflp_topic)
        if object_bbox_src == "dxnet":
            dynamic_objs_dict = self.parse_dynamic_json(object_topic)
        else:
            dynamic_objs_dict = self.parse_sf_json(object_topic)

        for ts, xnet_json in sxnet_topic.items():
            timestamp = xnet_json["time_stamp"]["nsec"]
            time_arr.append(timestamp)
            boundaries2d = self.parse_xnet_json(xnet_json)
            nearest_left_point, nearest_right_point = self.find_nearest_left_right_boundary_point(boundaries2d)
            nearest_time = 0
            nearest_time_gap = 1e99
            for time_, _ in localpose_dic.items():
                time_gap = abs(time_ - timestamp)
                if time_gap < nearest_time_gap:
                    nearest_time = time_
                    nearest_time_gap = time_gap
            nearest_time_ego_pos = localpose_dic[nearest_time]

            nearest_time_gap = 1e99
            for time_, _ in dynamic_objs_dict.items():
                time_gap = abs(time_ - timestamp)
                if time_gap < nearest_time_gap:
                    nearest_time = time_
                    nearest_time_gap = time_gap
            current_dynamic_objs = dynamic_objs_dict[nearest_time]

            # 动态障碍物边界计算
            dynamic_left_bound, dynamic_right_bound = self.calculate_obstacle_boundary(
                current_dynamic_objs
            )
            
            nearest_left_point = (
                dynamic_left_bound
                if dynamic_left_bound[1] < nearest_left_point[1]
                else nearest_left_point
            )

            nearest_right_point = (
                dynamic_right_bound
                if dynamic_right_bound[1] > nearest_right_point[1]
                else nearest_right_point
            )
            
            # dynamic left point
            nearset_left_dynamic_point = self.trans_to_ego_axis(
                nearest_time_ego_pos, dynamic_left_bound
            )
            nearset_right_dynamic_point = self.trans_to_ego_axis(
                nearest_time_ego_pos, dynamic_right_bound
            )
            nearset_left_dynamic_points.append(nearset_left_dynamic_point)
            nearset_right_dynamic_points.append(nearset_right_dynamic_point)
            
            nearest_left_point_rel_ego = self.trans_to_ego_axis(
                nearest_time_ego_pos, nearest_left_point
            )
            nearest_right_point_rel_ego = self.trans_to_ego_axis(
                nearest_time_ego_pos, nearest_right_point
            )
            left_dis_arr.append(nearest_left_point[1])
            right_dis_arr.append(nearest_right_point[1])
            nearest_left_boundary_points.append(nearest_left_point_rel_ego)
            nearest_right_boundary_points.append(nearest_right_point_rel_ego)
            nearest_ego_traj_points.append(nearest_time_ego_pos)

        fig, ax = plt.subplots(figsize=(10, 8))
        nearest_left_boundary_points_x, nearest_left_boundary_points_y = zip(
            *nearest_left_boundary_points
        )
        nearest_right_boundary_points_x, nearest_right_boundary_points_y = zip(
            *nearest_right_boundary_points
        )
        nearest_time_ego_pos_x, nearest_time_ego_pos_y, _ = zip(*nearest_ego_traj_points)
        ax.scatter(
            nearest_left_boundary_points_x,
            nearest_left_boundary_points_y,
            s=1,
            color="blue",
            label="left",
        )
        ax.scatter(
            nearest_right_boundary_points_x,
            nearest_right_boundary_points_y,
            s=1,
            color="red",
            label="right",
        )

        # draw dynamic left and right points
        nearset_left_dynamic_points_x, nearset_left_dynamic_points_y = zip(
            *nearset_left_dynamic_points
        )
        nearset_right_dynamic_points_x, nearset_right_dynamic_points_y = zip(
            *nearset_right_dynamic_points
        )

        ax.scatter(
            nearest_time_ego_pos_x, nearest_time_ego_pos_y, s=1, color="black", label="ego"
        )

        ax.legend(prop={'size': 1})

        ax.set_aspect("equal", adjustable="box")
        ax.legend()
        ax.grid()

        plt.savefig(os.path.join(output_path, "range.png"))
        output_json = {}
        for left_range, right_range, step_time in zip(
            left_dis_arr, right_dis_arr, time_arr
        ):
            output_json_str = {"left_range": left_range, "right_range": right_range}
            output_json[step_time] = output_json_str
        with open(os.path.join(output_path, "range.json"), "w") as variable_name:
            variable_name.write(json.dumps(output_json))

        return output_json

    def trans_to_ego_axis(self, ego_pose, boundary_point):
        ego_x = ego_pose[0]
        ego_y = ego_pose[1]
        ego_yaw = ego_pose[2]
        bp_d = boundary_point[1]
        rel_x = bp_d * math.sin(ego_yaw) + ego_x
        rel_y = bp_d * math.cos(ego_yaw) + ego_y
        return [rel_x, rel_y]

    def parse_localpose_json(self, mflp_topic):
        ret = {}
        for ts, mflp in mflp_topic.items():
            localpose_json = mflp
            time_stamp = localpose_json["time_stamp"]["nsec"]
            x = localpose_json["mf_local_pose"]["pose"]["p"]["x"]
            y = localpose_json["mf_local_pose"]["pose"]["p"]["y"]
            ret[time_stamp] = [x, y]

        pre_x = 0
        pre_y = 0
        start_2_yaw = 0
        start_x = 0
        start_y = 0
        start_time = 0
        for i in sorted(ret):
            x = ret[i][0]
            y = ret[i][1]
            if start_x == 0 and start_y == 0:
                start_x = x
                start_y = y
                start_time = time_stamp
            x = x - start_x
            y = y - start_y
            yaw = math.atan2(y - pre_y, x - pre_x)
            if pre_x != 0 and pre_y != 0 and start_2_yaw == 0:
                start_2_yaw = yaw
            ret[i] = [x, y, yaw]
            pre_x = x
            pre_y = y
        ret[start_time][2] = start_2_yaw
        return ret

    def parse_sf_json(self, sf_topic):
        """解析动态障碍物JSON数据"""
        sf_objects = {}
        for _, sf in sf_topic.items():
            timestamp = sf["time_stamp"]["nsec"]
            if timestamp not in sf_objects:
                sf_objects[timestamp] = []
            converted_sf = convert_obj_to_rig(sf)
            for obj in converted_sf['dynamic_object_vector']:
                pos = obj["local_pose"]
                dim = obj["size"]

                sf_objects[timestamp].append(
                    {
                        "timestamp": timestamp,
                        "x": pos["x"],
                        "y": pos["y"],
                        "length": dim["length"],
                        "width": dim["width"],
                        "height": dim["height"],
                    }
                )
            
        return sf_objects

    def parse_dynamic_json(self, dxnet_topic):
        """解析动态障碍物JSON数据"""
        dynamic_objects = {}
        for _, dxnet in dxnet_topic.items():
            timestamp = dxnet["time_stamp"]["nsec"]
            if timestamp not in dynamic_objects:
                dynamic_objects[timestamp] = []
            
            for obj in dxnet['objects']:
                pos = obj["bbox"]["bbox3d"]["position"]["pt"]
                dim = obj["bbox"]["bbox3d"]["dimension"]["pt"]

                dynamic_objects[timestamp].append(
                    {
                        "timestamp": timestamp,
                        "x": pos["x"],
                        "y": pos["y"],
                        "length": dim["x"],
                        "width": dim["y"],
                        "height": dim["z"],
                    }
                )
            
        return dynamic_objects

    def find_nearest_left_right_boundary_point(self, boundaries2d):
        nearest_right_point = [0, 11]
        nearest_left_point = [0, -11]
        for id_, points2d in boundaries2d.items():
            for point in points2d:
                dx = point[0]
                dy = -point[1]
                if 1.988 / 2 < dy < nearest_right_point[1] and abs(dx) < (5.293 + 2) / 2:
                    nearest_right_point[1] = dy - 1.988 / 2
                if -1.988 / 2 > dy > nearest_left_point[1] and abs(dx) < (5.293 + 2) / 2:
                    nearest_left_point[1] = dy + 1.988 / 2
        nearest_left_point[0] = -nearest_left_point[0]
        nearest_left_point[1] = -nearest_left_point[1]
        nearest_right_point[0] = -nearest_right_point[0]
        nearest_right_point[1] = -nearest_right_point[1]
        return nearest_left_point, nearest_right_point

    def calculate_obstacle_boundary(self, current_dynamic_objs):
        nearest_right_point = [0, 11]
        nearest_left_point = [0, -11]
        for obstacle in current_dynamic_objs:
            dx = obstacle["x"]
            dy = -obstacle["y"]
            width = obstacle["width"]
            length = obstacle["length"]
            if (1.988 / 2 + width / 2) < dy < nearest_right_point[1] and abs(dx) < (
                5.293 / 2 + length / 2
            ):
                nearest_right_point[1] = dy - (1.988 / 2 + width / 2)
            if -(1.988 / 2 + width / 2) > dy > nearest_left_point[1] and abs(dx) < (
                5.293 / 2 + length / 2
            ):
                nearest_left_point[1] = dy + (1.988 / 2 + width / 2)
        nearest_left_point[0] = -nearest_left_point[0]
        nearest_left_point[1] = -nearest_left_point[1]
        nearest_right_point[0] = -nearest_right_point[0]
        nearest_right_point[1] = -nearest_right_point[1]
        return nearest_left_point, nearest_right_point

    def parse_xnet_json(self, xnet_json):
        boundaries2d = {}
        xnet_boundaries = xnet_json["boundaries"]
        for boundary_json in xnet_boundaries:
            if "ROAD_BOUNDARY" in boundary_json["ascription"] and "LANE_BOUNDARY" not in boundary_json["ascription"]:
                points2d = []
                for point_json in boundary_json["points"]:
                    points2d.append([point_json["x"], point_json["y"]])
                boundaries2d[boundary_json["id"]] = points2d
        return boundaries2d




