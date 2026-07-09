import os
import torch
import torch.nn.functional as F
from collections import defaultdict, deque
from typing import Dict, Tuple, Optional

class CameraFilterSmoother:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, 
                 window_size: int = 5,  # 时间窗口大小（10fps下5帧=0.5秒）
                 weight_type: str = "uniform",  # 时间权重类型（高斯/线性）
                 device: str = 'cuda',
                 adapt_window: bool = True,
                 adapt_threshold: float = 0.005,  # 帧间差异阈值（判断突变）
                 adapt_hysteresis: int = 2,  # 连续突变帧计数阈值
                 time_decay: float = 0.8):  # 历史平滑结果的惯性权重
        global_cls = CameraFilterSmoother
        if self.__class__ is not global_cls:
            raise ValueError(f"Imported CameraFilterSmoother class is not unique! Current class ID: {id(self.__class__)}, Global class ID: {id(global_cls)}")

        if hasattr(self, '_initialized'):
            return
        
        # 时间窗口参数
        self.window_size = window_size
        self.max_window_size = window_size
        self.min_window_size = max(2, window_size // 2)  # 最小窗口不小于2
        self.weight_type = weight_type
        self.device = device

        # 自适应窗口参数
        self.adapt_window = adapt_window
        self.adapt_threshold = adapt_threshold
        self.adapt_hysteresis = adapt_hysteresis  # 窗口调整的滞后帧数

        # 时间惯性参数
        self.time_decay = time_decay  # 越大越稳定，越小越灵敏
        self.time_decay_h = 0.5
        self.time_decay_s = 0.5
        self.time_decay_v = 0.8
        self.time_decay_refine = 0.8

        # 多相机缓存（每个相机独立维护历史）
        self.cache: Dict[str, Dict] = defaultdict(self._init_cache)
        self._initialized = True
        self.cam_id_ = None

        # 跟踪每个通道每一帧前景的平均值
        self.channel_avgs = list()
        self.channel_avgs_background = list()
        self.channel_avgs_smoothed = list()

    def _init_cache(self) -> Dict:
        return {
            'filters': deque(maxlen=self.max_window_size),  # 存储历史滤镜参数
            'refine': deque(maxlen=self.max_window_size),   # 存储历史refine参数
            'prev_smoothed_filters': None,  # 上一帧平滑后的滤镜结果
            'prev_smoothed_refine': None,   # 上一帧平滑后的refine结果
            'high_diff_cnt': 0,  # 连续超过差异阈值的帧数（用于自适应窗口）
            'prev_smoothed_value': None,  # 上一帧平滑后的Value通道结果
        }

    def _get_weights(self, current_window: int) -> torch.Tensor:
        """生成时间权重（最近帧权重更高，减少历史干扰）"""
        if current_window == 1:
            return torch.tensor([1.0], device=self.device)
        
        indices = torch.arange(current_window, device=self.device)
        if self.weight_type == "gaussian":
            # 高斯权重：峰值在最近帧，权重更集中
            sigma = current_window / 8.0  # 控制权重集中程度
            gauss = torch.exp(-0.5 * ((indices - (current_window - 1)) / sigma) ** 2)
            return gauss / gauss.sum()
        elif self.weight_type == "linear":
            # 线性权重：随帧序号递增，增强最近帧影响
            linear = torch.arange(1, current_window + 1, device=self.device) **1.5  # 指数增强
            return linear / linear.sum()
        elif self.weight_type == "uniform":
            # 均匀权重：所有帧等权重
            uniform = torch.ones(current_window, device=self.device)
            return uniform / uniform.sum()
        elif self.weight_type == "reverse_linear":
            # 反向线性权重：随帧序号递减，增强历史帧影响
            reverse_linear = torch.arange(current_window, 0, -1, device=self.device) **1.5  # 指数增强
            return reverse_linear / reverse_linear.sum()
        else:
            raise ValueError(f"不支持的权重类型: {self.weight_type}")

    def _get_adapted_window(self, cam_id: str, current_filters: torch.Tensor) -> int:
        """根据帧间差异动态调整时间窗口大小"""
        cache = self.cache[cam_id]
        prev_smoothed = cache['prev_smoothed_filters']
        high_diff_cnt = cache['high_diff_cnt']

        # 无历史时用初始窗口
        if prev_smoothed is None:
            return min(self.window_size, self.max_window_size)
        
        # 计算当前帧与上一平滑结果的MSE（衡量突变程度）
        mse = torch.mean((current_filters - prev_smoothed)** 2).item()
        
        if mse > self.adapt_threshold:
            # 差异过大：累加计数，连续达到阈值才缩小窗口（抑制频繁调整）
            high_diff_cnt += 1
            cache['high_diff_cnt'] = high_diff_cnt
            if high_diff_cnt >= self.adapt_hysteresis:
                return self.min_window_size
            else:
                return min(len(cache['filters']), self.max_window_size)
        else:
            # 差异正常：重置计数，窗口逐步增大
            cache['high_diff_cnt'] = 0
            return min(len(cache['filters']) + 1, self.max_window_size)

    def smooth(self, current_filters: torch.Tensor, current_refines: torch.Tensor, raw_mask: torch.Tensor, smooth_channels: str = "V") -> torch.Tensor:
        """
        核心平滑方法：支持对 V / S / H 或其任意组合进行时间维度平滑。
        
        Args:
            current_filters (torch.Tensor): [B, 22, H, W]
            smooth_channels (str): 要平滑的通道组合，字符串由 'V', 'S', 'H' 中的字符组成。
                                例如: "V", "VS", "VH", "VSH" 等。顺序无关。
        Returns:
            smoothed_filters (torch.Tensor): [B, 22, H, W]
        """
        cam_id = self.cam_id() or "default_cam"
        if self.cam_id() is None:
            import warnings
            warnings.warn("未调用set_cam_id设置相机ID，使用默认值'default_cam'")
        
        assert current_filters.dim() == 4, f"滤镜必须是4D张量[B, C, H, W]，实际形状: {current_filters.shape}"
        assert current_filters.shape[1] == 22, f"预期通道数为22，实际为{current_filters.shape[1]}"

        # 解析要平滑的通道
        smooth_V = 'V' in smooth_channels
        smooth_S = 'S' in smooth_channels
        smooth_H = 'H' in smooth_channels
        smooth_refine = True  # 始终平滑refine通道

        cache = self.cache[cam_id]
        
        # 获取或初始化各通道的历史队列和缓存
        filters_deque_V = cache.setdefault('filters_V', deque(maxlen=self.window_size))
        filters_deque_V_fore = cache.setdefault('filters_V_fore', deque(maxlen=self.window_size))
        filters_deque_S = cache.setdefault('filters_S', deque(maxlen=self.window_size))
        filters_deque_S_fore = cache.setdefault('filters_S_fore', deque(maxlen=self.window_size))
        filters_deque_H = cache.setdefault('filters_H', deque(maxlen=self.window_size))
        filters_deque_H_fore = cache.setdefault('filters_H_fore', deque(maxlen=self.window_size))
        filter_deque_refine_fore = cache.setdefault('refine_fore', deque(maxlen=self.window_size))

        # 提取各分量
        val = current_filters[:, 12:21, :, :]      # [B, 9, H, W]
        sat = current_filters[:, 21:22, :, :]    # [B, 1, H, W]
        hue = current_filters[:, 0:12, :, :]     # [B, 12, H, W]

        val_foreground_mean = (val * raw_mask).sum(dim=(2, 3)) / (raw_mask.sum(dim=(2, 3)) + 1e-6) # [B, 9]
        sat_foreground_mean = (sat * raw_mask).sum(dim=(2, 3)) / (raw_mask.sum(dim=(2, 3)) + 1e-6) # [B, 1]
        hue_foreground_mean = (hue * raw_mask).sum(dim=(2, 3)) / (raw_mask.sum(dim=(2, 3)) + 1e-6) # [B, 12]
        refine_foreground_mean = (current_refines * raw_mask).sum(dim=(2, 3)) / (raw_mask.sum(dim=(2, 3)) + 1e-6) # [B, C]
        
        if cam_id == 1:
            self.channel_avgs.append({
                'val': val_foreground_mean[0].cpu(),
                'sat': sat_foreground_mean[0].cpu(),
                'hue': hue_foreground_mean[0].cpu(),
                'refine': refine_foreground_mean[0].cpu(),
            })

            val_background_mean = (val * (1 - raw_mask)).sum(dim=(2, 3)) / ((1 - raw_mask).sum(dim=(2, 3)) + 1e-6)
            sat_background_mean = (sat * (1 - raw_mask)).sum(dim=(2, 3)) / ((1 - raw_mask).sum(dim=(2, 3)) + 1e-6)
            hue_background_mean = (hue * (1 - raw_mask)).sum(dim=(2, 3)) / ((1 - raw_mask).sum(dim=(2, 3)) + 1e-6)
            refine_background_mean = (current_refines * (1 - raw_mask)).sum(dim=(2, 3)) / ((1 - raw_mask).sum(dim=(2, 3)) + 1e-6)
            self.channel_avgs_background.append({
                'val': val_background_mean[0].cpu(),
                'sat': sat_background_mean[0].cpu(),
                'hue': hue_background_mean[0].cpu(),
                'refine': refine_background_mean[0].cpu(),
            })

        def _smooth_channel(deque_fore, current, key_prefix):
            if len(deque_fore) == 0:
                return current
        
            # apply deque_fore to current smoothing
            # 1. convert deque [maxlen, B, C] to tensor [maxlen, B, C, H, W], broadcast mean value to H, W
            # 假设 deque_fore 存的是 [B, C]（全局统计量）
            history = torch.stack(list(deque_fore), dim=0)  # [T, B, C]
            maxlen, B, C = history.shape
            _, _, H, W = current.shape

            # 广播到全图
            history_full = history.view(maxlen, B, C, 1, 1).expand(-1, -1, -1, H, W)  # [T, B, C, H, W]

            # 获取时间权重
            weights = self._get_weights(maxlen)  # [T]
            weights = weights.view(maxlen, 1, 1, 1, 1)  # [T, 1, 1, 1, 1]

            # 2. weighted sum
            smoothed = (history_full * weights).sum(dim=0)  # [B, C, H, W]
            # 3. simple apply smoothed to current
            if key_prefix == 'val':
                return (self.time_decay_v * smoothed + (1 - self.time_decay_v) * current)
            elif key_prefix == 'sat':
                return (self.time_decay_s * smoothed + (1 - self.time_decay_s) * current)
            elif key_prefix == 'hue':
                return (self.time_decay_h * smoothed + (1 - self.time_decay_h) * current)
            elif key_prefix == 'refine':
                return (self.time_decay_refine * smoothed + (1 - self.time_decay_refine) * current)
            else:
                raise ValueError(f"未知的通道前缀: {key_prefix}")

        # 对指定通道做平滑
        smoothed_val = _smooth_channel(filters_deque_V_fore, val, 'val') if smooth_V else val
        smoothed_sat = _smooth_channel(filters_deque_S_fore, sat, 'sat') if smooth_S else sat
        smoothed_hue = _smooth_channel(filters_deque_H_fore, hue, 'hue') if smooth_H else hue
        smoothed_refine = _smooth_channel(filter_deque_refine_fore, current_refines, 'refine')

        # 更新历史队列（仅对要平滑的通道）
        if smooth_V:
            filters_deque_V.append(val.to(self.device))
            filters_deque_V_fore.append(val_foreground_mean.to(self.device))
        if smooth_S:
            filters_deque_S.append(sat.to(self.device))
            filters_deque_S_fore.append(sat_foreground_mean.to(self.device))
        if smooth_H:
            filters_deque_H.append(hue.to(self.device))
            filters_deque_H_fore.append(hue_foreground_mean.to(self.device))
        if smooth_refine:
            filter_deque_refine_fore.append(refine_foreground_mean.to(self.device))

        if cam_id == 1:
            smoothed_val_foreground_mean = (smoothed_val * raw_mask).sum(dim=(2, 3)) / (raw_mask.sum(dim=(2, 3)) + 1e-6)
            smoothed_sat_foreground_mean = (smoothed_sat * raw_mask).sum(dim=(2, 3)) / (raw_mask.sum(dim=(2, 3)) + 1e-6)
            smoothed_hue_foreground_mean = (smoothed_hue * raw_mask).sum(dim=(2, 3)) / (raw_mask.sum(dim=(2, 3)) + 1e-6)
            smoothed_refine_foreground_mean = (smoothed_refine * raw_mask).sum(dim=(2, 3)) / (raw_mask.sum(dim=(2, 3)) + 1e-6)

            self.channel_avgs_smoothed.append({
                'val': smoothed_val_foreground_mean[0].cpu(),
                'sat': smoothed_sat_foreground_mean[0].cpu(),
                'hue': smoothed_hue_foreground_mean[0].cpu(),
                'refine': smoothed_refine_foreground_mean[0].cpu(),
            })

        # 重组
        smoothed_filters = torch.cat([smoothed_hue, smoothed_val, smoothed_sat], dim=1)  # [B, 22, H, W]
        return smoothed_filters, smoothed_refine

    def display_channel_avgs_plot(self, saved_dir: str):
        if os.path.exists(saved_dir) is False:
            os.makedirs(saved_dir, exist_ok=True)

        """显示各通道前景平均值随时间变化的曲线图（仅相机ID为0时记录）"""
        import matplotlib.pyplot as plt

        if len(self.channel_avgs) == 0:
            print("没有可用的通道平均值数据进行绘图。")
            return
        
        # HSV各存一张图
        # value 9个通道，一个通道一个子图 (3x3)
        # sat 1个通道，一张图就好
        # hue 12个通道，一个通道一个子图 (4x3)

        # 绘制 Value 通道, background也画上,dashed line
        fig, axes = plt.subplots(3, 3, figsize=(15, 12))
        fig.suptitle("Value Smooth", fontsize=16)
        for i in range(9):
            ax = axes[i // 3, i % 3]
            vals = [entry['val'][i].item() for entry in self.channel_avgs]
            vals_smoothed = [entry['val'][i].item() for entry in self.channel_avgs_smoothed]
            vals_background = [entry['val'][i].item() for entry in self.channel_avgs_background]
            ax.plot(vals, label='raw', color='blue', alpha=0.5)
            ax.plot(vals_smoothed, label='smoothed', color='orange')
            ax.plot(vals_background, label='background', color='green', alpha=0.5, linestyle='--')
            ax.set_title(f'Value Channel {i}')
            ax.set_xlabel('frame')
            ax.set_ylabel('foreground average')
            ax.legend()
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plot_path = os.path.join(saved_dir, "channel_value_foreground_avg.png")
        plt.savefig(plot_path)
        plt.close()     

        # 绘制 Saturation 通道
        plt.figure(figsize=(8, 6))
        plt.title("Saturation Smooth", fontsize=16)
        sats = [entry['sat'][0].item() for entry in self.channel_avgs]
        sats_smoothed = [entry['sat'][0].item() for entry in self.channel_avgs_smoothed]
        sats_background = [entry['sat'][0].item() for entry in self.channel_avgs_background]
        plt.plot(sats, label='raw', color='blue', alpha=0.5)
        plt.plot(sats_smoothed, label='smoothed', color='orange')
        plt.plot(sats_background, label='background', color='green', alpha=0.5, linestyle='--')
        plt.xlabel('frame')
        plt.ylabel('foreground average')
        plt.legend()
        plot_path = os.path.join(saved_dir, "channel_saturation_foreground_avg.png")
        plt.savefig(plot_path)
        plt.close()

        # 绘制 Hue 通道
        fig, axes = plt.subplots(4, 3, figsize=(15, 16))
        fig.suptitle("Hue Smooth", fontsize=16)
        for i in range(12):
            ax = axes[i // 3, i % 3]
            hues = [entry['hue'][i].item() for entry in self.channel_avgs]
            hues_smoothed = [entry['hue'][i].item() for entry in self.channel_avgs_smoothed]
            hues_background = [entry['hue'][i].item() for entry in self.channel_avgs_background]
            ax.plot(hues, label='raw', color='blue', alpha=0.5)
            ax.plot(hues_smoothed, label='smoothed', color='orange')
            ax.plot(hues_background, label='background', color='green', alpha=0.5, linestyle='--')
            ax.set_title(f'Hue Channel {i}')
            ax.set_xlabel('frame')
            ax.set_ylabel('foreground average')
            ax.legend()
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plot_path = os.path.join(saved_dir, "channel_hue_foreground_avg.png")
        plt.savefig(plot_path)
        plt.close()

        # 绘制 Refine 通道
        plt.figure(figsize=(8, 6))
        plt.title("Refine Smooth", fontsize=16)
        refines = [entry['refine'][0].item() for entry in self.channel_avgs]
        refines_smoothed = [entry['refine'][0].item() for entry in self.channel_avgs_smoothed]
        refines_background = [entry['refine'][0].item() for entry in self.channel_avgs_background]
        plt.plot(refines, label='raw', color='blue', alpha=0.5)
        plt.plot(refines_smoothed, label='smoothed', color='orange')
        plt.plot(refines_background, label='background', color='green', alpha=0.5, linestyle='--')
        plt.xlabel('frame')
        plt.ylabel('foreground average')
        plt.legend()
        plot_path = os.path.join(saved_dir, "channel_refine_foreground_avg.png")
        plt.savefig(plot_path)
        plt.close()

        print(f"通道前景平均值曲线图已保存到: {plot_path}")

    def set_cam_id(self, cam_id: str):
        """设置当前相机ID（多相机场景下区分缓存）"""
        self.cam_id_ = cam_id

    def cam_id(self):
        """获取当前相机ID"""
        return self.cam_id_

    def reset_cache(self, cam_id: str = None) -> None:
        """重置指定相机的缓存（切换场景时使用）"""
        if cam_id:
            if cam_id in self.cache:
                self.cache[cam_id]['prev_smoothed_filters'] = None
                self.cache[cam_id]['prev_smoothed_refine'] = None
                self.cache[cam_id]['prev_smoothed_value'] = None
                self.cache[cam_id]['filters'].clear()
                self.cache[cam_id]['refine'].clear()
                self.cache[cam_id]['high_diff_cnt'] = 0  # 重置差异计数
        else:
            self.cache.clear()  # 重置所有相机缓存