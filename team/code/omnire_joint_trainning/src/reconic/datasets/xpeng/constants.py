import enum

VERSION = "v1.0.0"


SEMANTIC_CLASSES = {
    0: "Bird",
    1: "Ground_Animal",
    2: "Curb",
    3: "Fence",
    4: "Guard_Rail",
    5: "Barrier",
    6: "Wall",
    7: "Bike_lane",
    8: "CrossWalk_Palin",
    9: "Curb_Cut",
    10: "Parking",
    11: "Pedestrian_Area",
    12: "Rail_Track",
    13: "Road",
    14: "Service_Lane",
    15: "Sidewalk",
    16: "Bridge",
    17: "Building",
    18: "Tunnel",
    19: "Person",
    20: "Bicyclist",
    21: "Motorcyclist",
    22: "OtherRider",
    23: "CrossWalk_Marker",
    24: "General_Marker",
    25: "Mountain",
    26: "Sand",
    27: "Sky",
    28: "Snow",
    29: "Terrain",
    30: "Vegetation",
    31: "Water",
    32: "Banner",
    33: "Bench",
    34: "Bike_Rack",
    35: "Billboard",
    36: "Catch_Basin",
    37: "CCTV_Camera",
    38: "Fire_Hydrant",
    39: "Junction_Box",
    40: "Mailbox",
    41: "Manhole",
    42: "Phone_Booth",
    43: "Pothole",
    44: "StreetLight",
    45: "Pole",
    46: "TrafficSignFrame",
    47: "UtilityPole",
    48: "TrafficLight",
    49: "TrafficSign_Back",
    50: "TrafficSigh_Front",
    51: "Trash_Can",
    52: "Bicycle",
    53: "Boat",
    54: "Bus",
    55: "Car",
    56: "Caravan",
    57: "Motorcycle",
    58: "On_Rails",
    59: "OtherVehicle",
    60: "Trailer",
    61: "Truck",
    62: "WheeledSlow",
    63: "CarMount",
    64: "EgoVehicle",
    65: "Unlabeled",
}


DATASET_CLASSES_IN_SEMANTIC = {
    "VEHICLE": [52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65],
    "HUMAN": [0, 1, 19, 20, 21, 22],
    "GROUND": [7, 8, 13, 14, 23, 24, 41, 10],
    "SKY": [27],
    "TRAFFICLIGHT": [48],
}


class SemanticType(enum.IntEnum):
    DEFAULT = 0
    GROUND = 1
    SKY = 2
    VEHICLE = 3
    HUMAN = 4
    TRAFFICLIGHT = 5


class VehicleModel(enum.Enum):
    F30 = 50
    E38A = 43
    E28A = 21
    E38 = 40
    H93 = 60
    F57 = 70
    E38B = 203
    F30B = 206
    H93AS = 231
    XP5_201 = 201
    XP5_205 = 205
    XP5_269 = 269
    XP5_247 = 247
    XP5_239 = 239
    XP5_229 = 229
    XP5_243 = 243
    XP5_238 = 238
    XP5_268 = 268
    XP5_245 = 245
    XP5_281 = 281
    XP5_284 = 284
    XP5_244 = 244
    XP5_283 = 283
    XP5_270 = 270
    XP5_304 = 304
    D01M = 212


VEHICLE_MODEL_CATEGORY_MAP = {
    VehicleModel.F57: "vision_vehicle_model",
    VehicleModel.E38B: "vision_vehicle_model",
    VehicleModel.F30B: "vision_vehicle_model",
    VehicleModel.H93AS: "vision_vehicle_model",
    VehicleModel.XP5_201: "vision_vehicle_model",
    VehicleModel.XP5_205: "vision_vehicle_model",
    VehicleModel.XP5_269: "vision_vehicle_model",
    VehicleModel.XP5_247: "vision_vehicle_model",
    VehicleModel.XP5_239: "vision_vehicle_model",
    VehicleModel.XP5_229: "vision_vehicle_model",
    VehicleModel.XP5_243: "vision_vehicle_model",
    VehicleModel.XP5_238: "vision_vehicle_model",
    VehicleModel.XP5_268: "vision_vehicle_model",
    VehicleModel.XP5_245: "vision_vehicle_model",
    VehicleModel.XP5_281: "vision_vehicle_model",
    VehicleModel.XP5_284: "vision_vehicle_model",
    VehicleModel.XP5_244: "vision_vehicle_model",
    VehicleModel.XP5_283: "vision_vehicle_model",
    VehicleModel.XP5_270: "vision_vehicle_model",
    VehicleModel.XP5_304: "vision_vehicle_model",
    VehicleModel.D01M: "vision_vehicle_model",
    VehicleModel.F30: "default",
    VehicleModel.E38A: "default",
    VehicleModel.E28A: "default",
    VehicleModel.E38: "default",
    VehicleModel.H93: "default",
}

VEHICLE_MODEL_CATEGORIES = {
    "vision_vehicle_model": [
        VehicleModel.F57,
        VehicleModel.E38B,
        VehicleModel.F30B,
        VehicleModel.H93AS,
        VehicleModel.XP5_201,
        VehicleModel.XP5_205,
        VehicleModel.XP5_269,
        VehicleModel.XP5_247,
        VehicleModel.XP5_239,
        VehicleModel.XP5_229,
        VehicleModel.XP5_243,
        VehicleModel.XP5_238,
        VehicleModel.XP5_268,
        VehicleModel.XP5_245,
        VehicleModel.XP5_281,
        VehicleModel.XP5_284,
        VehicleModel.XP5_244,
        VehicleModel.XP5_283,
        VehicleModel.XP5_270,
        VehicleModel.XP5_304,
        VehicleModel.D01M,
    ],
    "default": [
        VehicleModel.F30,
        VehicleModel.E38A,
        VehicleModel.E28A,
        VehicleModel.E38,
        VehicleModel.H93
    ]
}