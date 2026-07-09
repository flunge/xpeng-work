import yaml
import argparse
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, Arrow
from matplotlib.animation import FuncAnimation
import numpy as np
from typing import Dict, List, Any, Tuple, Optional
import time
import os

FIXED_Z = 1.1

class TrajectoryVisualizer:
    def __init__(self, config_path: str):
        """初始化轨迹可视化器"""
        self.config_path = config_path
        self.data = self._load_config()
        self.frame_count = len(self.data['results']['timestamps'])
        self.fig, self.ax = plt.subplots(figsize=(10, 8))
        self.objects = {}  # 存储对象的图形元素
        self.selected_gids = []  # 存储用户选择的GID
        self.anchor_matrix = np.eye(4)  # 锚点变换矩阵
        self.ego_positions = []  # 存储自车位置
        self.ego_rotations = []  # 存储自车旋转角度
        self.manual_trajectory = []  # 存储手动绘制的轨迹点
        self.is_drawing = False  # 是否处于绘制状态
        self.interpolation_points = 100  # 每段插值点数
        self.max_speed = 10.0  # 默认最大速度 (m/s)
        self.min_speed = 1.0  # 默认最小速度 (m/s)
        self.constant_speed = 5.0  # 固定速度
        self.is_processed = False  # 轨迹是否已处理
        self.frame_data = []  # 存储生成的帧数据
        self.drag_start = None  # 用于拖动画面
        self.time_labels = []  # 存储时间标注
        self.ego_time_labels = []  # 存储自车时间标注
        self.obj_elapsed_time_set = set()  # 用于避免重复时间标注

    def _load_config(self) -> Dict[str, Any]:
        """加载YAML配置文件"""
        try:
            with open(self.config_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            print(f"错误: 文件 '{self.config_path}' 未找到")
            exit(1)
        except yaml.YAMLError as e:
            print(f"错误: 解析YAML文件时出错: {e}")
            exit(1)

    def _parse_anchor_pose(self) -> None:
        """解析锚点变换矩阵"""
        if 'anchor_pose' not in self.data['results']:
            print("警告: YAML文件中未找到锚点数据(anchor_pose)，将使用单位矩阵作为锚点")
            return
            
        # 从YAML数据构建4x4变换矩阵
        anchor_data = self.data['results']['anchor_pose']
        self.anchor_matrix = np.array(anchor_data)

    def _parse_ego_poses(self) -> None:
        """解析自车的位姿数据，并应用锚点变换"""
        if 'ego_frame_poses' not in self.data['results']:
            print("警告: YAML文件中未找到自车轨迹数据(ego_frame_poses)")
            return
            
        ego_poses = self.data['results']['ego_frame_poses']
        
        for pose_matrix in ego_poses:
            # 从YAML数据构建4x4变换矩阵
            ego_matrix = np.array(pose_matrix)
            
            # 应用锚点变换：全局坐标 = 锚点变换 × 自车局部坐标
            global_matrix = np.dot(self.anchor_matrix, ego_matrix)
            
            # 提取平移向量（第四列的前三个元素）
            translation = [global_matrix[0, 3], global_matrix[1, 3], global_matrix[2, 3]]
            self.ego_positions.append(translation)
            
            # 提取旋转矩阵（前3x3子矩阵）
            rotation_matrix = global_matrix[:3, :3]
            
            # 计算偏航角(yaw) - 假设主要绕z轴旋转
            yaw = np.arctan2(rotation_matrix[1, 0], rotation_matrix[0, 0])
            self.ego_rotations.append(yaw)

        # print("自车位置数据size:", len(self.ego_positions))
        # print(self.ego_positions)

    def _quaternion_to_yaw(self, quaternion: List[float]) -> float:
        """将四元数转换为偏航角(yaw)"""
        w, x, y, z = quaternion
        # 由于数据中x和y为0，简化计算
        yaw = 2 * np.arctan2(z, w)
        return yaw

    def _get_object_rectangle(self, obj: Dict[str, Any], frame_index: int) -> Tuple[float, float, float, float, float]:
        """获取对象的矩形表示参数，考虑锚点和自车位置"""
        x_rel, y_rel, z_rel = obj['translation']
        length, width, height = obj['size']
        yaw_obj = self._quaternion_to_yaw(obj['rotation'])
        
        x_global = x_rel
        y_global = y_rel
        yaw_global = yaw_obj
        return x_global, y_global, length, width, yaw_global

    def _draw_object(self, obj: Dict[str, Any], frame_index: int) -> None:
        """绘制单个对象"""
        gid = obj['gid']
        center_x, center_y, length, width, yaw = self._get_object_rectangle(obj, frame_index)
        
        # 创建矩形
        rect = Rectangle(
            (center_x - length/2, center_y - width/2),
            length, width,
            angle=np.degrees(yaw),
            fill=True,
            alpha=0.7
        )
        
        # 根据移动状态设置颜色
        if obj['is_moving']:
            rect.set_color('blue')  # 移动对象为蓝色
        else:
            rect.set_color('red')   # 静止对象为红色
            
        # 添加到图表
        self.ax.add_patch(rect)
        
        # 添加标签
        # self.ax.text(
        #     center_x, center_y, 
        #     f"GID: {gid}",
        #     horizontalalignment='center',
        #     verticalalignment='center',
        #     color='white',
        #     fontweight='bold',
        #     fontsize=8
        # )
        
        # 存储对象的图形元素
        self.objects[gid] = rect

        # 显示时间戳
        # timestamps = self.data['results']['timestamps']
        # start_time = float(timestamps[0])
        # elapsed_time_set = set()  # 用于避免重复时间标注
        # for i in range(len(timestamps)):
        #     elapsed_time = (float(timestamps[i]) - start_time) / 1e9  # 转换为秒
        #     elapsed_time_str = f"{elapsed_time:.0f}s"
        #     if elapsed_time % 1 < 1e-1 and elapsed_time_str not in elapsed_time_set:  # 每隔1秒显示一次时间
        #         x, y, _ = self.ego_positions[i]
        #         label = self.ax.text(x, y, elapsed_time_str, fontsize=8, color='black')
        #         self.time_labels.append(label)
        #         elapsed_time_set.add(elapsed_time_str)

        # 显示旁车轨迹的时间戳
        timestamps = self.data['results']['timestamps']
        start_time = float(timestamps[0])
        elapsed_time = (float(timestamps[frame_index]) - start_time) / 1e9  # 转换为秒
        elapsed_time_str = f"{elapsed_time:.0f}s"
        if elapsed_time % 1 < 1e-1 and elapsed_time_str not in self.obj_elapsed_time_set:  # 每隔1秒显示一次时间
            label = self.ax.text(center_x, center_y, elapsed_time_str, fontsize=8, color='black')
            self.time_labels.append(label)
            self.obj_elapsed_time_set.add(elapsed_time_str)

    def _draw_ego_trajectory(self) -> None:
        """绘制自车轨迹"""
        if not self.ego_positions:
            return
            
        # 清理旧的自车时间标注
        for text in self.ego_time_labels:
            text.remove()
        self.ego_time_labels.clear()
            
        # 提取x和y坐标
        x_coords = [pos[0] for pos in self.ego_positions]
        y_coords = [pos[1] for pos in self.ego_positions]
        
        # 绘制轨迹线
        self.ax.plot(x_coords, y_coords, 'g-', linewidth=2, label='ego trajectory')
        
        # 绘制所有自车位姿点
        for i, (x, y) in enumerate(zip(x_coords, y_coords)):
            # 绘制位置点
            self.ax.plot(x, y, 'go', markersize=4)
            
            # 只在关键点（如起点和终点）添加方向指示
            if i == 0 or i == len(x_coords) - 1 or i % 5 == 0:
                if i < len(self.ego_rotations):
                    yaw = self.ego_rotations[i]
                    # 绘制方向箭头
                    arrow_length = 1.0
                    self.ax.arrow(
                        x, y,
                        arrow_length * np.cos(yaw), arrow_length * np.sin(yaw),
                        head_width=0.3, head_length=0.4, fc='green', ec='green'
                    )
        
        # 绘制当前位置（使用绿色星形标记）
        if len(self.ego_positions) > 0:
            current_x, current_y, _ = self.ego_positions[-1]
            self.ax.plot(current_x, current_y, 'g*', markersize=12, label='ego position')
            
            # 绘制自车轮廓（使用较大的绿色矩形）
            if len(self.ego_rotations) > 0:
                current_yaw = self.ego_rotations[-1]
            else:
                current_yaw = 0
                
            ego_rect = Rectangle(
                (current_x - 1.5, current_y - 0.75),  # 假设自车尺寸为3m×1.5m
                3, 1.5,
                angle=np.degrees(current_yaw),
                fill=True,
                color='green',
                alpha=0.5
            )
            self.ax.add_patch(ego_rect)

        # 显示时间戳
        timestamps = self.data['results']['timestamps']
        start_time = float(timestamps[0])
        elapsed_time_set = set()  # 用于避免重复时间标注
        for i in range(len(timestamps)):
            elapsed_time = (float(timestamps[i]) - start_time) / 1e9  # 转换为秒
            elapsed_time_str = f"{elapsed_time:.0f}s"
            if elapsed_time % 1 < 1e-1 and elapsed_time_str not in elapsed_time_set:  # 每隔1秒显示一次时间
                x, y, _ = self.ego_positions[i]
                label = self.ax.text(x, y, elapsed_time_str, fontsize=8, color='black')

                self.ego_time_labels.append(label)

                elapsed_time_set.add(elapsed_time_str)

    def _setup_plot(self) -> None:
        """设置图表"""
        self.ax.set_aspect('equal')
        self.ax.set_xlabel('X (m)')
        self.ax.set_ylabel('Y (m)')
        # self.ax.set_title('轨迹可视化')
        self.ax.grid(True)
        
        # 添加图例
        moving_patch = Rectangle((0, 0), 1, 1, color='blue', alpha=0.7)
        stationary_patch = Rectangle((0, 0), 1, 1, color='red', alpha=0.7)
        ego_patch = Rectangle((0, 0), 1, 1, color='green', alpha=0.5)

        # 添加手动轨迹图例
        manual_line, = self.ax.plot([], [], 'm--', linewidth=2)
        manual_point, = self.ax.plot([], [], 'mo', markersize=6)
        
        # self.ax.legend([moving_patch, stationary_patch, ego_patch], 
        #              ['移动对象', '静止对象', '自车'])
        
        manual_line, = self.ax.plot([], [], 'm-', linewidth=2, alpha=0.8)
        manual_point, = self.ax.plot([], [], 'mo', markersize=6)
        frame_point, = self.ax.plot([], [], 'c.', markersize=4, alpha=0.7)
        
        # 添加rotation图例
        rotation_arrow = Arrow(0, 0, 1, 0, width=0.2, color='purple')
        rotation_rect = Rectangle((0, 0), 1, 1, color='purple', alpha=0.5)
        
        # self.ax.legend(
        #     [moving_patch, stationary_patch, ego_patch, manual_line, manual_point, frame_point, rotation_arrow, rotation_rect],
        #     ['移动对象', '静止对象', '自车', '平滑轨迹', '手动轨迹点', '帧采样点', '方向角', '生成的车辆姿态']
        # )

    def _on_key_press(self, event):
        """键盘按键事件处理函数"""
        if event.key == 'backspace' and self.manual_trajectory:
            # 删除最近一次添加的旁车轨迹点及其到达时间
            self.manual_trajectory.pop()
            print("删除最近一次添加的旁车轨迹点")

            # 生成并更新平滑轨迹
            self._generate_smooth_trajectory()
            self._calculate_orientation_and_speed()
            self._generate_frame_data()

            # 实时更新手动轨迹
            self.ax.clear()
            self._setup_plot()
            self._redraw_all()
            self.fig.canvas.draw_idle()

    def visualize(self, selected_gids: Optional[List[int]] = None, save_dir="") -> None:
        """可视化轨迹数据"""
        if not selected_gids:
            selected_gids = []
        if len(selected_gids) == 0:
            selected_gids.append(-1)
        self.selected_gids = selected_gids
        
        # 解析锚点数据
        self._parse_anchor_pose()
        
        # 解析自车轨迹数据（应用锚点变换）
        self._parse_ego_poses()
        
        # 设置图表
        self._setup_plot()
        
        # 获取所有帧中的对象
        frames = self.data['results']['annotations']['frames']
        
        # 绘制所有帧中的对象和自车轨迹
        for frame_index, frame in enumerate(frames):
            # 绘制所有对象
            for obj in frame['objects']:
                # 如果指定了GID，则只绘制指定的GID
                if selected_gids and obj['gid'] not in selected_gids:
                    continue
                    
                self._draw_object(obj, frame_index)
        
        # 绘制自车轨迹
        self._draw_ego_trajectory()

        # 设置鼠标事件监听
        self.fig.canvas.mpl_connect('button_press_event', self._on_click)
        self.fig.canvas.mpl_connect('button_release_event', self._on_release)
        self.fig.canvas.mpl_connect('motion_notify_event', self._on_motion)
        self.fig.canvas.mpl_connect('key_press_event', self._on_key_press)
        
        # 自动调整坐标轴范围
        all_x = []
        all_y = []
        
        # 添加所有对象的坐标
        for frame_index, frame in enumerate(frames):
            for obj in frame['objects']:
                if selected_gids and obj['gid'] not in selected_gids:
                    continue
                    
                x, y, _, _, _ = self._get_object_rectangle(obj, frame_index)
                length, width, _ = obj['size']
                
                # 考虑对象尺寸，确保完整显示
                all_x.extend([x - length/2, x + length/2])
                all_y.extend([y - width/2, y + width/2])
        
        # 添加自车轨迹的坐标
        for x, y, _ in self.ego_positions:
            all_x.extend([x - 1.5, x + 1.5])  # 自车尺寸
            all_y.extend([y - 0.75, y + 0.75])
        
        # 添加锚点位置
        anchor_x, anchor_y = self.anchor_matrix[0, 3], self.anchor_matrix[1, 3]
        all_x.extend([anchor_x - 0.5, anchor_x + 0.5])
        all_y.extend([anchor_y - 0.5, anchor_y + 0.5])
        
        if all_x and all_y:
            # 添加一些边距
            margin = 5
            self.ax.set_xlim(min(all_x) - margin, max(all_x) + margin)
            self.ax.set_ylim(min(all_y) - margin, max(all_y) + margin)
        
        # 标记锚点位置
        if all_x and all_y:
            self.ax.plot(anchor_x, anchor_y, 'ko', markersize=8, label='anchor')
            self.ax.text(anchor_x+1, anchor_y+1, 'anchor', fontsize=10)

        plt.tight_layout()
        plt.show()

        # write final visualization
        if save_dir:
            self.fig.savefig(os.path.join(save_dir, "model_visualization.png"), dpi=300)

    def _draw_manual_trajectory(self) -> None:
        """绘制手动添加的轨迹（包括原始点和平滑曲线）"""
        # 清理旧的旁车时间标注
        for text in self.time_labels:
            text.remove()
        self.time_labels.clear()
            
        # 绘制原始点
        if len(self.manual_trajectory) > 0:
            x_coords = [p[0] for p in self.manual_trajectory]
            y_coords = [p[1] for p in self.manual_trajectory]
            self.ax.plot(x_coords, y_coords, 'mo', markersize=6, label='手动轨迹点')
            
            # 添加起点和终点标记
            self.ax.plot(x_coords[0], y_coords[0], 'ms', markersize=8, label='起点')
            self.ax.plot(x_coords[-1], y_coords[-1], 'md', markersize=8, label='终点')
        
        # 绘制平滑曲线
        if len(self.smooth_trajectory) > 1:
            x_smooth = [p[0] for p in self.smooth_trajectory]
            y_smooth = [p[1] for p in self.smooth_trajectory]
            self.ax.plot(x_smooth, y_smooth, 'm-', linewidth=2, alpha=0.8, label='平滑轨迹')

            # # 绘制方向箭头
            # if hasattr(self, 'orientations'):
            #     arrow_length = 1.0
            #     for i in range(0, len(self.smooth_trajectory), max(1, len(self.smooth_trajectory)//20)):
            #         x, y = self.smooth_trajectory[i]
            #         orientation = self.orientations[i]
            #         self.ax.arrow(
            #             x, y,
            #             arrow_length * np.cos(orientation), arrow_length * np.sin(orientation),
            #             head_width=0.3, head_length=0.4, fc='purple', ec='purple'
            #         )

            # 绘制帧采样点
        if self.frame_data:
            frame_x = [data['position'][0] for data in self.frame_data]
            frame_y = [data['position'][1] for data in self.frame_data]
            self.ax.plot(frame_x, frame_y, 'c.', markersize=4, alpha=0.7, label='帧采样点')
            
            # 每隔几帧显示一个帧号
            # for i in range(0, len(self.frame_data), max(1, len(self.frame_data)//10)):
            #     x, y = self.frame_data[i]['position']
            #     self.ax.text(x, y, f"{i}", fontsize=8, color='cyan')

            # 可视化rotation（方向角）
            self._visualize_rotation()

        # 在绘制帧采样点后添加：
        if self.smooth_trajectory and self.frame_data:
            # 绘制平滑轨迹与采样点的连接线（用于调试）
            for data in self.frame_data:
                x, y = data['position']
                self.ax.plot([x], [y], 'y+', markersize=5, alpha=0.5)  # 用黄色十字标记采样点

        # 显示旁车轨迹的时间戳
        timestamps = self.data['results']['timestamps']
        start_time = float(timestamps[0])
        elapsed_time_set = set()  # 用于避免重复时间标注
        for i, frame in enumerate(self.frame_data):
            elapsed_time = (float(timestamps[i]) - start_time) / 1e9  # 转换为秒
            elapsed_time_str = f"{elapsed_time:.0f}s"
            if elapsed_time % 1 < 1e-1 and elapsed_time_str not in elapsed_time_set:  # 每隔1秒显示一次时间
                x, y = frame['position']
                label = self.ax.text(x, y, elapsed_time_str, fontsize=8, color='black')
                self.time_labels.append(label)
                elapsed_time_set.add(elapsed_time_str)

    def _redraw_all(self) -> None:
        """重绘所有元素"""
        frames = self.data['results']['annotations']['frames']
        
        # 重绘对象
        for frame_index, frame in enumerate(frames):
            for obj in frame['objects']:
                if self.selected_gids and obj['gid'] not in self.selected_gids:
                    continue
                self._draw_object(obj, frame_index)
        
        # 重绘自车轨迹
        self._draw_ego_trajectory()
        
        # 重绘手动轨迹
        self._draw_manual_trajectory()
        
        # 标记锚点
        anchor_x, anchor_y = self.anchor_matrix[0, 3], self.anchor_matrix[1, 3]
        self.ax.plot(anchor_x, anchor_y, 'ko', markersize=8, label='锚点')

    def _on_click(self, event) -> None:
        """鼠标点击事件处理函数"""
        if event.inaxes != self.ax:
            return
            
        # 左键点击添加点
        if event.key == 'alt' and event.button == 1:
            self.drag_start = (event.xdata, event.ydata)
        elif event.button == 1:
            self.manual_trajectory.append((event.xdata, event.ydata))
            self.is_drawing = True
            print(f"添加点: ({event.xdata:.2f}, {event.ydata:.2f})")

            # 生成并更新平滑轨迹
            self._generate_smooth_trajectory()
            
            # 实时更新手动轨迹
            self.ax.clear()
            self._setup_plot()
            self._redraw_all()
            self.fig.canvas.draw_idle()
        
        # 右键点击结束绘制
        elif event.button == 3:
            if self.is_drawing:
                print(f"手动轨迹绘制完成，共{len(self.manual_trajectory)}个点")
                
                self.is_drawing = False

                # 计算方向和速度
                self._calculate_orientation_and_speed()
                
                # 生成帧数据
                self._generate_frame_data()
                
                # 更新图表
                self.ax.clear()
                self._setup_plot()
                self._redraw_all()
                self.fig.canvas.draw_idle()
    
    def _on_release(self, event):
        """鼠标释放事件处理函数"""
        self.drag_start = None

    def _on_motion(self, event):
        """鼠标移动事件处理函数"""
        if event.inaxes != self.ax or self.drag_start is None:
            return
        dx = event.xdata - self.drag_start[0]
        dy = event.ydata - self.drag_start[1]
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()
        self.ax.set_xlim(xlim[0] - dx, xlim[1] - dx)
        self.ax.set_ylim(ylim[0] - dy, ylim[1] - dy)
        self.drag_start = (event.xdata, event.ydata)
        self.fig.canvas.draw_idle()

    def _generate_smooth_trajectory(self) -> None:
        points = self.manual_trajectory
        if len(points) < 2:
            self.smooth_trajectory = points
            return
        
        # 修复：在曲率较大的手动点之间插入额外点，增强弯道精度
        refined_points = []
        for i in range(len(points) - 1):
            refined_points.append(points[i])
            # 计算当前段的曲率（两点之间的角度变化）
            if i > 0 and i < len(points) - 2:
                # 前一段方向
                dx_prev = points[i][0] - points[i-1][0]
                dy_prev = points[i][1] - points[i-1][1]
                dir_prev = np.arctan2(dy_prev, dx_prev)
                # 当前段方向
                dx_curr = points[i+1][0] - points[i][0]
                dy_curr = points[i+1][1] - points[i][1]
                dir_curr = np.arctan2(dy_curr, dx_curr)
                # 角度差（曲率）
                angle_diff = abs(dir_curr - dir_prev)
                if angle_diff > np.pi:
                    angle_diff = 2 * np.pi - angle_diff
                # 曲率大则插入更多点（角度差 > 30度）
                if angle_diff > np.pi / 6:
                    num_extra = int(angle_diff * 5)  # 按角度差动态增加点
                    for t in np.linspace(0, 1, num_extra + 2)[1:-1]:
                        x = points[i][0] + t * dx_curr
                        y = points[i][1] + t * dy_curr
                        refined_points.append((x, y))
        refined_points.append(points[-1])
        points = refined_points  # 使用细分后的手动点
        
        # 后续插值逻辑不变（计算距离、u参数、三次样条）
        distances = [0.0]
        for i in range(1, len(points)):
            dx = points[i][0] - points[i-1][0]
            dy = points[i][1] - points[i-1][1]
            distances.append(distances[-1] + np.sqrt(dx*dx + dy*dy))
        u = [d / distances[-1] for d in distances] if distances[-1] > 0 else [i/(len(points)-1) for i in range(len(points))]
        x, y = [p[0] for p in points], [p[1] for p in points]
        
        smooth_points = []
        for i in range(len(points) - 1):
            u_segment = np.linspace(u[i], u[i+1], self.interpolation_points)
            for ui in u_segment:
                t = (ui - u[i]) / (u[i+1] - u[i])
                h00, h10, h01, h11 = 2*t**3-3*t**2+1, t**3-2*t**2+t, -2*t**3+3*t**2, t**3-t**2
                
                # 导数估计（沿用之前的稳健逻辑）
                if i == 0:
                    if len(points) > 2:
                        m0 = ((x[2]-x[0])/(u[2]-u[0]), (y[2]-y[0])/(u[2]-u[0]))
                    else:
                        m0 = ((x[1]-x[0])/(u[1]-u[0]), (y[1]-y[0])/(u[1]-u[0]))
                else:
                    m0 = ((x[i+1]-x[i-1])/(u[i+1]-u[i-1]), (y[i+1]-y[i-1])/(u[i+1]-u[i-1]))
                
                if i == len(points)-2:
                    if len(points) > 2:
                        m1 = ((x[-1]-x[-3])/(u[-1]-u[-3]), (y[-1]-y[-3])/(u[-1]-u[-3]))
                    else:
                        m1 = ((x[-1]-x[-2])/(u[-1]-u[-2]), (y[-1]-y[-2])/(u[-1]-u[-2]))
                else:
                    m1 = ((x[i+2]-x[i])/(u[i+2]-u[i]), (y[i+2]-y[i])/(u[i+2]-u[i]))
                
                xi = h00 * x[i] + h10 * (u[i+1]-u[i]) * m0[0] + h01 * x[i+1] + h11 * (u[i+1]-u[i]) * m1[0]
                yi = h00 * y[i] + h10 * (u[i+1]-u[i]) * m0[1] + h01 * y[i+1] + h11 * (u[i+1]-u[i]) * m1[1]
                smooth_points.append((xi, yi))
        
        smooth_points.append(points[-1])
        self.smooth_trajectory = smooth_points

    def _calculate_orientation_and_speed(self) -> None:
        if len(self.smooth_trajectory) < 3:  # 至少需要3个点才能计算稳定的中间方向
            # super()._calculate_orientation_and_speed()  # 调用原逻辑处理少点情况
            return
        
        orientations = []
        speeds = []
        
        for i in range(len(self.smooth_trajectory)):
            if i == 0:
                # 起点：用下一点方向
                dx = self.smooth_trajectory[i+1][0] - self.smooth_trajectory[i][0]
                dy = self.smooth_trajectory[i+1][1] - self.smooth_trajectory[i][1]
                orientation = np.arctan2(dy, dx)
            elif i == len(self.smooth_trajectory) - 1:
                # 终点：用上一点方向
                dx = self.smooth_trajectory[i][0] - self.smooth_trajectory[i-1][0]
                dy = self.smooth_trajectory[i][1] - self.smooth_trajectory[i-1][1]
                orientation = np.arctan2(dy, dx)
            else:
                # 中间点：用三点拟合圆弧的切线方向（更平滑）
                # 取i-1, i, i+1三点
                x_prev, y_prev = self.smooth_trajectory[i-1]
                x_curr, y_curr = self.smooth_trajectory[i]
                x_next, y_next = self.smooth_trajectory[i+1]
                
                # 计算前向和后向向量
                dx_prev = x_curr - x_prev
                dy_prev = y_curr - y_prev
                dx_next = x_next - x_curr
                dy_next = y_next - y_curr
                
                # 用加权平均（距离越近权重越大）
                len_prev = np.sqrt(dx_prev**2 + dy_prev**2) + 1e-6
                len_next = np.sqrt(dx_next**2 + dy_next**2) + 1e-6
                weight_prev = len_next / (len_prev + len_next)  # 后向距离长则前向权重高
                weight_next = len_prev / (len_prev + len_next)
                
                # 加权平均方向向量
                dx_avg = weight_prev * dx_prev + weight_next * dx_next
                dy_avg = weight_prev * dy_prev + weight_next * dy_next
                orientation = np.arctan2(dy_avg, dx_avg)
            
            # 处理角度周期性（同原逻辑）
            if i > 0:
                prev_orient = orientations[i-1]
                delta = orientation - prev_orient
                if delta > np.pi:
                    orientation -= 2 * np.pi
                elif delta < -np.pi:
                    orientation += 2 * np.pi
            
            orientations.append(orientation)
            
            # 使用固定速度
            speeds.append(self.constant_speed)
        
        self.orientations = orientations
        self.speeds = speeds

    def _generate_frame_data(self) -> None:
        if not self.smooth_trajectory or not hasattr(self, 'orientations') or not hasattr(self, 'speeds'):
            print("请先完成轨迹绘制并计算方向和速度")
            return
        
        # 重新计算累计距离（增加校验）
        cumulative_distances = [0.0]
        for i in range(1, len(self.smooth_trajectory)):
            dx = self.smooth_trajectory[i][0] - self.smooth_trajectory[i-1][0]
            dy = self.smooth_trajectory[i][1] - self.smooth_trajectory[i-1][1]
            dist = np.sqrt(dx**2 + dy**2)
            cumulative_distances.append(cumulative_distances[-1] + dist)
        total_length = cumulative_distances[-1]
        if total_length == 0:
            self.frame_data = [{'position': self.smooth_trajectory[0], 'orientation': 0.0, 'speed': 0.0, 'frame_index': i} for i in range(self.frame_count)]
            return
        
        frame_data = []
        for frame in range(self.frame_count):
            # 目标距离（确保最后一帧准确）
            target_distance = total_length * (frame / (self.frame_count - 1)) if self.frame_count > 1 else total_length
            
            # 二分查找（增加边界保护）
            import bisect
            idx = bisect.bisect_left(cumulative_distances, target_distance) - 1
            idx = max(0, min(idx, len(cumulative_distances) - 2))  # 限制在有效范围
            
            # 计算比例（处理浮点数精度问题）
            seg_dist = cumulative_distances[idx + 1] - cumulative_distances[idx]
            ratio = (target_distance - cumulative_distances[idx]) / seg_dist if seg_dist > 1e-6 else 0.0
            ratio = max(0.0, min(1.0, ratio))  # 强制比例在[0,1]，避免溢出
            
            # 插值位置（增加精度处理）
            x = self.smooth_trajectory[idx][0] + ratio * (self.smooth_trajectory[idx+1][0] - self.smooth_trajectory[idx][0])
            y = self.smooth_trajectory[idx][1] + ratio * (self.smooth_trajectory[idx+1][1] - self.smooth_trajectory[idx][1])
            # 修复：保留6位小数，减少浮点数误差
            x = round(x, 6)
            y = round(y, 6)
            
            # 方向角插值（增加最终归一化）
            orient1 = self.orientations[idx]
            orient2 = self.orientations[idx + 1]
            delta = orient2 - orient1
            if delta > np.pi:
                orient2 -= 2 * np.pi
            elif delta < -np.pi:
                orient2 += 2 * np.pi
            orientation = orient1 + ratio * (orient2 - orient1)
            # 最终归一化到[-π, π]
            orientation = (orientation + np.pi) % (2 * np.pi) - np.pi
            
            # 使用固定速度
            speed = self.constant_speed
            
            frame_data.append({
                'position': (x, y),
                'orientation': orientation,
                'speed': speed,
                'frame_index': frame
            })
        
        self.frame_data = frame_data
        self.is_processed = True
        print(f"成功生成{len(frame_data)}帧轨迹数据")

    # 获取最近的自车位置
    def _get_nearest_ego_position(self, position: Tuple[float, float]) -> Tuple[float, float, float]:
        """获取最近的自车位置"""
        if not self.ego_positions:
            return (0.0, 0.0, 0.0)
        
        # 计算与所有自车位置的距离
        distances = [np.linalg.norm(np.array(pos[:2]) - np.array(position)) for pos in self.ego_positions]
        nearest_index = np.argmin(distances)
        return self.ego_positions[nearest_index][:3]

    def save_frame_data(self, update_gid: int, add_object: bool) -> None:
        """将帧数据保存为YAML文件"""
        from datetime import datetime
        # 生成一个毫秒级时间戳作为文件名的一部分
        timestamp_ms = time.time_ns() // 1_000_000
        # 判断输出目录是否存在
        if not os.path.exists('./output'):
            os.makedirs('./output')
        output_path = f"./output/output_{timestamp_ms}.yaml"
        if not self.frame_data:
            print("没有可用的帧数据，请先完成轨迹绘制")
            return
        
        if not self.data:
            print("没有有效的YAML数据，请先加载配置文件")
            return
        
        new_data = self.data.copy()

        update_obj_gid = update_gid
        frames = new_data['results']['annotations']['frames']
        # 先保存目标对象的基础数据
        target_obj_data = None
        for frame in frames:
            for obj in frame['objects']:
                if obj['gid'] == update_obj_gid:
                    target_obj_data = obj.copy()
                    break
            if target_obj_data:
                break
        
        if target_obj_data is not None and add_object:
            print(f"找到GID为{update_obj_gid}的目标对象，不能插入相同的GID")
            return
        
        if not add_object and not target_obj_data:
            print(f"未找到GID为{update_obj_gid}的目标对象，无法更新")
            return
        if not add_object:
            for i, frame in enumerate(frames):
                for j, obj in enumerate(frame['objects']):
                    if obj['gid'] == update_obj_gid:
                        new_obj = obj.copy()
                        # 修改 translation
                        new_frame_data = self.frame_data[i]
                        nearest_ego_position = self._get_nearest_ego_position(new_frame_data['position'])
                        new_obj['translation'] = [float(new_frame_data['position'][0]), float(new_frame_data['position'][1]), float(nearest_ego_position[2] + FIXED_Z)]
                        # 修改 rotation
                        yaw = new_frame_data['orientation']
                        # 转换为四元数
                        qw = float(np.cos(yaw/2))
                        qx = 0.0
                        qy = 0.0
                        qz = float(np.sin(yaw/2))
                        new_obj['rotation'] = [qw, qx, qy, qz]
                        # 修改 speed
                        new_obj['speed'] = float(new_frame_data['speed'])
                        new_obj['size'] = [float(target_obj_data['size'][0]), float(target_obj_data['size'][1]), float(target_obj_data['size'][2])]
                        frame['objects'][j] = new_obj
                        # 输出new obj
                        print(f"更新帧 {i} 中的目标对象 GID {update_obj_gid} 的数据")
                        print(new_obj)
                        print(frame['objects'][j])    
        else:
            for i, frame in enumerate(frames):
                new_frame_data = self.frame_data[i]
                new_obj = {}
                nearest_ego_position = self._get_nearest_ego_position(new_frame_data['position'])
                new_obj['translation'] = [float(new_frame_data['position'][0]), float(new_frame_data['position'][1]), float(nearest_ego_position[2] + FIXED_Z)]
                # 修改 rotation
                yaw = new_frame_data['orientation']
                # 转换为四元数
                qw = float(np.cos(yaw/2))
                qx = 0.0
                qy = 0.0
                qz = float(np.sin(yaw/2))
                new_obj['rotation'] = [qw, qx, qy, qz]
                # new_obj['speed'] = float(new_frame_data['speed'])
                # TODO: 这里需要根据实际情况调整对象的属性
                new_obj['size'] = [float(4.5), float(1.7), float(1.9)]
                new_obj['is_moving'] = True  # 假设所有对象都是移动的
                new_obj['gid'] = update_obj_gid  # 确保GID一致
                new_obj['type'] = 'car'
                frame['objects'].append(new_obj)
        
        # 保存到YAML文件
        try:
            with open(output_path, 'w') as f:
                # yaml.dump(new_data, f, sort_keys=False, default_flow_style=None)
                yaml.dump(
                    new_data,
                    f,
                    default_flow_style=False,
                    indent=2,
                    sort_keys=False,
                    allow_unicode=True,
                )
            print(f"成功保存{len(self.frame_data)}帧数据到 {output_path}")
        except Exception as e:
            print(f"保存文件时出错: {e}")

    def _visualize_rotation(self) -> None:
        """可视化生成的rotation（方向角）"""
        if not self.frame_data:
            return
            
        # 绘制车辆轮廓和方向箭头
        vehicle_length = 4.5  # 车辆长度
        vehicle_width = 2.0   # 车辆宽度
        
        # 每隔几帧绘制一个车辆
        for i in range(0, len(self.frame_data), max(1, len(self.frame_data)//60)):
        # for i in range(0, len(self.frame_data)):
            frame = self.frame_data[i]
            x, y = frame['position']
            yaw = frame['orientation']
            
            # 创建车辆矩形
            rect = Rectangle(
                (x - vehicle_length/2, y - vehicle_width/2),
                vehicle_length, vehicle_width,
                angle=np.degrees(yaw),
                fill=True,
                color='purple',
                alpha=0.5
            )
            self.ax.add_patch(rect)
            
            # 添加车辆方向箭头
            arrow_length = vehicle_length * 0.6
            self.ax.arrow(
                x, y,
                arrow_length * np.cos(yaw), arrow_length * np.sin(yaw),
                head_width=0.5, head_length=0.7, fc='purple', ec='purple'
            )
            
            # 添加帧号标签
            # self.ax.text(
            #     x, y - vehicle_width/2 - 0.5,
            #     f"Frame {frame['frame_index']}",
            #     horizontalalignment='center',
            #     verticalalignment='center',
            #     fontsize=8,
            #     color='purple'
            # )
    
def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='轨迹数据可视化工具')
    parser.add_argument('config_path', type=str, help='YAML配置文件路径')
    parser.add_argument('--gids', type=int, nargs='+', help='指定要显示的GID列表，用空格分隔')
    parser.add_argument('--update_gid', type=int, help='更新的GID')
    parser.add_argument('--add_object', type=bool, default=True, help='是否添加新对象')

    args = parser.parse_args()
    
    visualizer = TrajectoryVisualizer(args.config_path)
    visualizer.visualize(args.gids)

    # 如果指定了输出路径，保存帧数据
    visualizer.save_frame_data(update_gid=args.update_gid, add_object=args.add_object)

if __name__ == "__main__":
    main()    