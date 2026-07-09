#include <torch/extension.h>

#include "Ops.h"
#include "Cameras.h"

// 方案C：不注册 pybind 枚举/类型，改为暴露 int 接口，内部 cast。

static std::tuple<at::Tensor, at::Tensor, at::Tensor, at::Tensor, at::Tensor>
projection_ewa_3dgs_fused_fwd_i(
    const at::Tensor means,
    const c10::optional<at::Tensor> covars,
    const c10::optional<at::Tensor> quats,
    const c10::optional<at::Tensor> scales,
    const c10::optional<at::Tensor> opacities,
    const at::Tensor viewmats,
    const at::Tensor Ks,
    const uint32_t image_width,
    const uint32_t image_height,
    const float eps2d,
    const float near_plane,
    const at::Tensor far_plane,
    const float radius_clip,
    const bool calc_compensations,
    const int camera_model_int // 0=pinhole, 1=ortho, 2=fisheye
) {
    xpeng_raster::CameraModelType cam = xpeng_raster::CameraModelType::PINHOLE;
    if (camera_model_int == 1) cam = xpeng_raster::CameraModelType::ORTHO;
    else if (camera_model_int == 2) cam = xpeng_raster::CameraModelType::FISHEYE;
    return xpeng_raster::projection_ewa_3dgs_fused_fwd(
        means, covars, quats, scales, opacities, viewmats, Ks,
        image_width, image_height, eps2d, near_plane, far_plane,
        radius_clip, calc_compensations, cam
    );
}

PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {
    // 不再注册 CameraModelType，避免与 gsplat 冲突
    m.def("projection_ewa_3dgs_fused_fwd_i", &projection_ewa_3dgs_fused_fwd_i);
    m.def("rasterize_to_pixels_3dgs_fwd", &xpeng_raster::rasterize_to_pixels_3dgs_fwd);
    m.def("intersect_tile", &xpeng_raster::intersect_tile);
    m.def("intersect_offset", &xpeng_raster::intersect_offset);
}
