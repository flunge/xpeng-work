import enum

VERSION = 'v1.0.0'

SEMANTIC_CLASSES = {
    0: 'Bird', 1: 'Ground_Animal', 2: 'Curb', 3: 'Fence', 4: 'Guard_Rail', 5: 'Barrier', 6: 'Wall', 
    7: 'Bike_lane', 8: 'CrossWalk_Palin', 9: 'Curb_Cut', 10: 'Parking', 11: 'Pedestrian_Area', 12: 'Rail_Track', 
    13: 'Road', 14: 'Service_Lane', 15: 'Sidewalk', 16: 'Bridge', 17: 'Building', 18: 'Tunnel', 19: 'Person', 20: 'Bicyclist', 
    21: 'Motorcyclist', 22: 'OtherRider', 23: 'CrossWalk_Marker', 24: 'General_Marker', 25: 'Mountain', 26: 'Sand', 
    27: 'Sky', 28: 'Snow', 29: 'Terrain', 30: 'Vegetation', 31: 'Water', 32: 'Banner', 33: 'Bench', 34: 'Bike_Rack', 
    35: 'Billboard', 36: 'Catch_Basin', 37: 'CCTV_Camera', 38: 'Fire_Hydrant', 39: 'Junction_Box', 40: 'Mailbox', 
    41: 'Manhole', 42: 'Phone_Booth', 43: 'Pothole', 44: 'StreetLight', 45: 'Pole', 46: 'TrafficSignFrame', 
    47: 'UtilityPole', 48: 'TrafficLight', 49: 'TrafficSign_Back', 50: 'TrafficSigh_Front', 51: 'Trash_Can', 
    52: 'Bicycle', 53: 'Boat', 54: 'Bus', 55: 'Car', 56: 'Caravan', 57: 'Motorcycle', 58: 'On_Rails', 59: 'OtherVehicle', 
    60: 'Trailer', 61: 'Truck', 62: 'WheeledSlow', 63: 'CarMount', 64: 'EgoVehicle', 65: 'Unlabeled'
}


DATASET_CLASSES_IN_SEMANTIC = {
    'GROUND': [7, 8, 13, 14, 23, 24, 41, 10, 36, 43],
    'SKY': [27],
    'VEHICLE': [52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65],
    'HUMAN': [0, 1, 19, 20, 21, 22],
    'ROADSIDE': [2, 3, 4, 5, 6, 9, 11, 12, 15, 16, 18, 26, 28]
}


class SemanticType(enum.IntEnum):
    DEFAULT = 0
    GROUND = 1
    SKY = 2
    VEHICLE = 3
    HUMAN = 4
    ROADSIDE = 5