package(default_visibility = ["//visibility:public"])

load("@xpilot_build_tools//rules/pkg:xpilot_release.bzl", "xpilot_release_package")

xpilot_release_package(
    name = "simworld_render_pkg",
    srcs = glob(["sim_interface/**"]) + 
           glob(["models/street_gaussians/**"]) + 
           glob(["omnire_joint_trainning/src/**"]) +
           glob(["models/difix/**"]) +
           glob(["models/CLIP-IQA/**"]),  
    strip_prefix = ".",
)