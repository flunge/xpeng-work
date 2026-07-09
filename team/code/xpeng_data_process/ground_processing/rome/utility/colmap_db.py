import os
import sys
import sqlite3
import re
import numpy as np
from typing import Optional, List, Dict, Any
import logging
from pathlib import Path
from tqdm import tqdm


IS_PYTHON3 = sys.version_info[0] >= 3

MAX_IMAGE_ID = 2 ** 31 - 1

CREATE_CAMERAS_TABLE = """CREATE TABLE IF NOT EXISTS cameras (
    camera_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    model INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    params BLOB,
    prior_focal_length INTEGER NOT NULL)"""

CREATE_DESCRIPTORS_TABLE = """CREATE TABLE IF NOT EXISTS descriptors (
    image_id INTEGER PRIMARY KEY NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    data BLOB,
    FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE)"""

CREATE_IMAGES_TABLE = """CREATE TABLE IF NOT EXISTS images (
    image_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    name TEXT NOT NULL UNIQUE,
    camera_id INTEGER NOT NULL,
    prior_qw REAL,
    prior_qx REAL,
    prior_qy REAL,
    prior_qz REAL,
    prior_tx REAL,
    prior_ty REAL,
    prior_tz REAL,
    CONSTRAINT image_id_check CHECK(image_id >= 0 and image_id < {}),
    FOREIGN KEY(camera_id) REFERENCES cameras(camera_id))
""".format(
    MAX_IMAGE_ID
)

CREATE_TWO_VIEW_GEOMETRIES_TABLE = """
CREATE TABLE IF NOT EXISTS two_view_geometries (
    pair_id INTEGER PRIMARY KEY NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    data BLOB,
    config INTEGER NOT NULL,
    F BLOB,
    E BLOB,
    H BLOB,
    qvec BLOB,
    tvec BLOB)
"""

CREATE_KEYPOINTS_TABLE = """CREATE TABLE IF NOT EXISTS keypoints (
    image_id INTEGER PRIMARY KEY NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    data BLOB,
    FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE)
"""

CREATE_MATCHES_TABLE = """CREATE TABLE IF NOT EXISTS matches (
    pair_id INTEGER PRIMARY KEY NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    data BLOB)"""

CREATE_NAME_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS index_name ON images(name)"
)

CREATE_ALL = "; ".join(
    [
        CREATE_CAMERAS_TABLE,
        CREATE_IMAGES_TABLE,
        CREATE_KEYPOINTS_TABLE,
        CREATE_DESCRIPTORS_TABLE,
        CREATE_MATCHES_TABLE,
        CREATE_TWO_VIEW_GEOMETRIES_TABLE,
        CREATE_NAME_INDEX,
    ]
)


def image_ids_to_pair_id(image_id1, image_id2):
    if image_id1 > image_id2:
        image_id1, image_id2 = image_id2, image_id1
    return image_id1 * MAX_IMAGE_ID + image_id2


def pair_id_to_image_ids(pair_id):
    image_id2 = pair_id % MAX_IMAGE_ID
    image_id1 = (pair_id - image_id2) / MAX_IMAGE_ID
    return image_id1, image_id2


def array_to_blob(array):
    if IS_PYTHON3:
        return array.tostring()
    else:
        return np.getbuffer(array)


def blob_to_array(blob, dtype, shape=(-1,)):
    if blob is None:
        return np.array([])
    if IS_PYTHON3:
        return np.fromstring(blob, dtype=dtype).reshape(*shape)
    else:
        return np.frombuffer(blob, dtype=dtype).reshape(*shape)


class COLMAPDatabase(sqlite3.Connection):
    @staticmethod
    def connect(database_path):
        return sqlite3.connect(database_path, factory=COLMAPDatabase)

    def __init__(self, *args, **kwargs):
        super(COLMAPDatabase, self).__init__(*args, **kwargs)

        self.create_tables = lambda: self.executescript(CREATE_ALL)
        self.create_cameras_table = lambda: self.executescript(
            CREATE_CAMERAS_TABLE
        )
        self.create_descriptors_table = lambda: self.executescript(
            CREATE_DESCRIPTORS_TABLE
        )
        self.create_images_table = lambda: self.executescript(
            CREATE_IMAGES_TABLE
        )
        self.create_two_view_geometries_table = lambda: self.executescript(
            CREATE_TWO_VIEW_GEOMETRIES_TABLE
        )
        self.create_keypoints_table = lambda: self.executescript(
            CREATE_KEYPOINTS_TABLE
        )
        self.create_matches_table = lambda: self.executescript(
            CREATE_MATCHES_TABLE
        )
        self.create_name_index = lambda: self.executescript(CREATE_NAME_INDEX)

    def add_camera(
        self,
        model,
        width,
        height,
        params,
        prior_focal_length=False,
        camera_id=None,
    ):
        params = np.asarray(params, np.float64)
        cursor = self.execute(
            "INSERT INTO cameras VALUES (?, ?, ?, ?, ?, ?)",
            (
                camera_id,
                model,
                width,
                height,
                array_to_blob(params),
                prior_focal_length,
            ),
        )
        return cursor.lastrowid

    def add_image(
        self,
        name,
        camera_id,
        prior_q=np.full(4, np.NaN),
        prior_t=np.full(3, np.NaN),
        image_id=None,
    ):
        cursor = self.execute(
            "INSERT INTO images VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                image_id,
                name,
                camera_id,
                prior_q[0],
                prior_q[1],
                prior_q[2],
                prior_q[3],
                prior_t[0],
                prior_t[1],
                prior_t[2],
            ),
        )
        return cursor.lastrowid

    def add_keypoints(self, image_id, keypoints):
        assert len(keypoints.shape) == 2
        assert keypoints.shape[1] in [2, 4, 6]

        keypoints = np.asarray(keypoints, np.float32)
        self.execute(
            "INSERT INTO keypoints VALUES (?, ?, ?, ?)",
            (image_id,) + keypoints.shape + (array_to_blob(keypoints),),
        )

    def add_descriptors(self, image_id, descriptors):
        descriptors = np.ascontiguousarray(descriptors, np.uint8)
        self.execute(
            "INSERT INTO descriptors VALUES (?, ?, ?, ?)",
            (image_id,) + descriptors.shape + (array_to_blob(descriptors),),
        )

    def add_matches(self, image_id1, image_id2, matches):
        assert len(matches.shape) == 2
        assert matches.shape[1] == 2

        if image_id1 > image_id2:
            matches = matches[:, ::-1]

        pair_id = image_ids_to_pair_id(image_id1, image_id2)
        matches = np.asarray(matches, np.uint32)
        self.execute(
            "INSERT INTO matches VALUES (?, ?, ?, ?)",
            (pair_id,) + matches.shape + (array_to_blob(matches),),
        )

    def add_two_view_geometry(
        self,
        image_id1,
        image_id2,
        matches,
        F=np.eye(3),
        E=np.eye(3),
        H=np.eye(3),
        qvec=np.array([1.0, 0.0, 0.0, 0.0]),
        tvec=np.zeros(3),
        config=2,
    ):
        assert len(matches.shape) == 2
        assert matches.shape[1] == 2

        if image_id1 > image_id2:
            matches = matches[:, ::-1]

        pair_id = image_ids_to_pair_id(image_id1, image_id2)
        matches = np.asarray(matches, np.uint32)
        F = np.asarray(F, dtype=np.float64)
        E = np.asarray(E, dtype=np.float64)
        H = np.asarray(H, dtype=np.float64)
        qvec = np.asarray(qvec, dtype=np.float64)
        tvec = np.asarray(tvec, dtype=np.float64)
        self.execute(
            "INSERT INTO two_view_geometries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pair_id,)
            + matches.shape
            + (
                array_to_blob(matches),
                config,
                array_to_blob(F),
                array_to_blob(E),
                array_to_blob(H),
                array_to_blob(qvec),
                array_to_blob(tvec),
            ),
        )

def get_image_ids(database_path: Path) -> Dict[str, int]:
    db = COLMAPDatabase.connect(database_path)
    images = {}
    for name, image_id in db.execute("SELECT name, image_id FROM images;"):
        images[name] = image_id
    db.close()
    return images

def get_image_ids_and_two_view_geo(database_path: Path) -> Dict[str, int]:
    db = COLMAPDatabase.connect(database_path)
    name_to_id = {}
    id_to_name = {}
    for name, image_id in db.execute("SELECT name, image_id FROM images;"):
        name_to_id[name] = image_id
        id_to_name[image_id] = name
    two_view_pairs = []
    for pair_id, data in db.execute("SELECT pair_id, data FROM two_view_geometries;"):
        if data is not None:
            two_view_pairs.append(pair_id)
    db.close()
    return name_to_id, id_to_name, two_view_pairs

def get_image_ids_and_two_view_geo_data(database_path: Path) -> Dict[str, int]:
    db = COLMAPDatabase.connect(database_path)
    name_to_id = {}
    id_to_name = {}
    for name, image_id in db.execute("SELECT name, image_id FROM images;"):
        name_to_id[name] = image_id
        id_to_name[image_id] = name
    two_view_data = {}
    for pair_id, data in db.execute("SELECT pair_id, data FROM two_view_geometries;"):
        if data is not None:
            two_view_data[pair_id] = blob_to_array(data, np.uint32, (-1, 2))
    keypoints = dict(
        (image_id, blob_to_array(data, np.float32, (-1, 2)))
        for image_id, data in db.execute(
            "SELECT image_id, data FROM keypoints"))
    db.close()
    return name_to_id, id_to_name, two_view_data, keypoints


def get_image_idx_and_camera_idx(database_path: Path) -> Dict[str, int]:
    db = COLMAPDatabase.connect(database_path)
    name_to_id = {}
    name_to_cam_id = {}
    for name, image_id, camera_id in db.execute("SELECT name, image_id, camera_id FROM images;"):
        name_to_id[name] = image_id
        name_to_cam_id[name] = camera_id

    db.close()
    return name_to_id, name_to_cam_id


def example_usage():
    import os
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--database_path", default="database.db")
    args = parser.parse_args()

    if os.path.exists(args.database_path):
        print("ERROR: database path already exists -- will not modify it.")
        return

    # Open the database.

    db = COLMAPDatabase.connect(args.database_path)

    # For convenience, try creating all the tables upfront.

    db.create_tables()

    # Create dummy cameras.

    model1, width1, height1, params1 = (
        0,
        1024,
        768,
        np.array((1024.0, 512.0, 384.0)),
    )
    model2, width2, height2, params2 = (
        2,
        1024,
        768,
        np.array((1024.0, 512.0, 384.0, 0.1)),
    )

    camera_id1 = db.add_camera(model1, width1, height1, params1)
    camera_id2 = db.add_camera(model2, width2, height2, params2)

    # Create dummy images.

    image_id1 = db.add_image("image1.png", camera_id1)
    image_id2 = db.add_image("image2.png", camera_id1)
    image_id3 = db.add_image("image3.png", camera_id2)
    image_id4 = db.add_image("image4.png", camera_id2)

    # Create dummy keypoints.
    #
    # Note that COLMAP supports:
    #      - 2D keypoints: (x, y)
    #      - 4D keypoints: (x, y, theta, scale)
    #      - 6D affine keypoints: (x, y, a_11, a_12, a_21, a_22)

    num_keypoints = 1000
    keypoints1 = np.random.rand(num_keypoints, 2) * (width1, height1)
    keypoints2 = np.random.rand(num_keypoints, 2) * (width1, height1)
    keypoints3 = np.random.rand(num_keypoints, 2) * (width2, height2)
    keypoints4 = np.random.rand(num_keypoints, 2) * (width2, height2)

    db.add_keypoints(image_id1, keypoints1)
    db.add_keypoints(image_id2, keypoints2)
    db.add_keypoints(image_id3, keypoints3)
    db.add_keypoints(image_id4, keypoints4)

    # Create dummy matches.

    M = 50
    matches12 = np.random.randint(num_keypoints, size=(M, 2))
    matches23 = np.random.randint(num_keypoints, size=(M, 2))
    matches34 = np.random.randint(num_keypoints, size=(M, 2))

    db.add_matches(image_id1, image_id2, matches12)
    db.add_matches(image_id2, image_id3, matches23)
    db.add_matches(image_id3, image_id4, matches34)

    # Commit the data to the file.

    db.commit()

    # Read and check cameras.

    rows = db.execute("SELECT * FROM cameras")

    camera_id, model, width, height, params, prior = next(rows)
    params = blob_to_array(params, np.float64)
    assert camera_id == camera_id1
    assert model == model1 and width == width1 and height == height1
    assert np.allclose(params, params1)

    camera_id, model, width, height, params, prior = next(rows)
    params = blob_to_array(params, np.float64)
    assert camera_id == camera_id2
    assert model == model2 and width == width2 and height == height2
    assert np.allclose(params, params2)

    # Read and check keypoints.

    keypoints = dict(
        (image_id, blob_to_array(data, np.float32, (-1, 2)))
        for image_id, data in db.execute("SELECT image_id, data FROM keypoints")
    )

    assert np.allclose(keypoints[image_id1], keypoints1)
    assert np.allclose(keypoints[image_id2], keypoints2)
    assert np.allclose(keypoints[image_id3], keypoints3)
    assert np.allclose(keypoints[image_id4], keypoints4)

    # Read and check matches.

    pair_ids = [
        image_ids_to_pair_id(*pair)
        for pair in (
            (image_id1, image_id2),
            (image_id2, image_id3),
            (image_id3, image_id4),
        )
    ]

    matches = dict(
        (pair_id_to_image_ids(pair_id), blob_to_array(data, np.uint32, (-1, 2)))
        for pair_id, data in db.execute("SELECT pair_id, data FROM matches")
    )

    assert np.all(matches[(image_id1, image_id2)] == matches12)
    assert np.all(matches[(image_id2, image_id3)] == matches23)
    assert np.all(matches[(image_id3, image_id4)] == matches34)

    # Clean up.

    db.close()

    if os.path.exists(args.database_path):
        os.remove(args.database_path)


def create_empty_db(database_path: Path):
    if database_path.exists():
        logging.warning('The database already exists, deleting it.')
        database_path.unlink()
    logging.info('Creating an empty database...')
    db = COLMAPDatabase.connect(database_path)
    db.create_tables()
    db.commit()
    db.close()

def import_images_from_folder(image_dir, database_path, cam_info_list):
    logging.info('Importing images into the database...')
    db = COLMAPDatabase.connect(database_path)
    cam_names = [name for name in os.listdir(image_dir) if re.match(r'cam\d+$', name)]
    cam_names.sort(key=lambda name: int(name[3:]))
    for cam_name in cam_names:
        if cam_name not in cam_info_list:
            continue
        cameraModel=cam_info_list[cam_name]['camera_model']
        width=cam_info_list[cam_name]['width']
        height=cam_info_list[cam_name]['height']
        params=np.array([cam_info_list[cam_name]['focal_length'], cam_info_list[cam_name]['cx'], cam_info_list[cam_name]['cy']])
        camera_id = db.add_camera(cameraModel, width, height, params)
        cam_path = os.path.join(image_dir, cam_name)
        image_names = [name for name in os.listdir(cam_path) if name.endswith('.png')]
        image_names.sort(key=lambda x: int(re.match(f'slice(\d+).png', x).group(1)))
        for image_name in image_names:
            name = '/'.join([cam_name, image_name])
            db.add_image(name, camera_id)

    db.commit()
    db.close()


def import_features(image_ids: Dict[str, int],
                    database_path: Path,
                    features: dict):
    logging.info('Importing features into the database...')
    db = COLMAPDatabase.connect(database_path)

    for image_name, image_id in image_ids.items():
        if image_name not in features:
            continue
        keypoints = features[image_name]['keypoints']
        keypoints += 0.5  # COLMAP origin
        db.add_keypoints(image_id, keypoints)

    db.commit()
    db.close()


def import_matches(image_ids: Dict[str, int],
                   database_path: Path,
                   pairs: List,
                   matches_dict: Path,
                   src_prefix: str = None,
                   tgt_prefix: str = None,
                   min_match_score: Optional[float] = None,
                   run_geometric_verification: bool = False):
    logging.info('Importing matches into the database...')

    db = COLMAPDatabase.connect(database_path)

    matched = set()
    for pair in pairs:
        name0, name1 = pair
        if (not name0 in image_ids) or (not name1 in image_ids):
            continue
        if src_prefix is not None and tgt_prefix is not None:
            id0, id1 = image_ids[src_prefix + '/' + name0], image_ids[tgt_prefix + '/' + name1]
        else:
            id0, id1 = image_ids[name0], image_ids[name1]
        if len({(id0, id1), (id1, id0)} & matched) > 0:
            continue

        if pair not in matches_dict:
            print('pair not in matches_dict!', pair)
            continue

        matches = matches_dict[pair]['matches0']
        scores = matches_dict[pair]['matching_scores0']
        idx = np.where(matches != -1)[0]
        matches = np.stack([idx, matches[idx]], -1)
        scores = scores[idx]

        if min_match_score:
            matches = matches[scores > min_match_score]

        db.add_matches(id0, id1, matches)
        matched |= {(id0, id1), (id1, id0)}

        if run_geometric_verification:
            db.add_two_view_geometry(id0, id1, matches)

    db.commit()
    db.close()

def import_cross_trip_matches(image_ids: Dict[str, int],
                   database_path: Path,
                   all_pairs: List,
                   all_matches_dict: List[Path],
                   all_src_prefix: List[str],
                   all_tgt_prefix: List[str],
                   min_match_score: Optional[float] = None,
                   run_geometric_verification: bool = False):

    logging.info('Importing cross trip matches into the database...')
    assert len(all_pairs) == len(all_matches_dict) == len(all_src_prefix) == len(all_tgt_prefix), \
        "List length are not equal!"

    db = COLMAPDatabase.connect(database_path)

    matched = set()
    for idx, pairs in enumerate(all_pairs):
        matches_dict = all_matches_dict[idx]
        src_prefix = all_src_prefix[idx]
        tgt_prefix = all_tgt_prefix[idx]
        for pair in pairs:
            name0, name1 = pair
            if src_prefix is not None and tgt_prefix is not None:
                id0, id1 = image_ids[src_prefix + '/' + name0], image_ids[tgt_prefix + '/' + name1]
            else:
                id0, id1 = image_ids[name0], image_ids[name1]
            if len({(id0, id1), (id1, id0)} & matched) > 0:
                continue

            if pair not in matches_dict:
                print('pair not in matches_dict!', pair)
                continue

            matches = matches_dict[pair]['matches0']
            scores = matches_dict[pair]['matching_scores0']
            idx = np.where(matches != -1)[0]
            matches = np.stack([idx, matches[idx]], -1)
            scores = scores[idx]

            if min_match_score:
                matches = matches[scores > min_match_score]

            db.add_matches(id0, id1, matches)
            matched |= {(id0, id1), (id1, id0)}

            if run_geometric_verification:
                db.add_two_view_geometry(id0, id1, matches)

    db.commit()
    db.close()


def add_image_prefix(database_path, image_prefix):
    db = COLMAPDatabase.connect(database_path)
    image_table_list = db.execute('SELECT * FROM images;').fetchall()
    for image_table in image_table_list:
        image_name = image_table[1]
        if image_name.startswith(image_prefix):
            continue
        cmd = 'UPDATE images SET name=\'{}\' where name=\'{}\''.format(os.path.join(image_prefix, image_name),
                                                                       image_name)
        db.execute(cmd)
    db.commit()
    db.close()


def load_match_from_db(database_path):
    ### Load matches from DB
    db = COLMAPDatabase.connect(database_path)
    keypoints = dict(
        (image_id, blob_to_array(data, np.float32, (-1, 2)))
        for image_id, data in db.execute(
            "SELECT image_id, data FROM keypoints"))
    images_name = dict(
        (image_id, name)
        for image_id, name in db.execute("SELECT image_id, name FROM images"))
    all_matches = dict(
        (pair_id_to_image_ids(pair_id),
            blob_to_array(data, np.uint32, (-1, 2)))
        for pair_id, data in db.execute("SELECT pair_id, data FROM matches")
            if data is not None)
    inlier_matches = dict(
        (pair_id_to_image_ids(pair_id),
            blob_to_array(data, np.uint32, (-1, 2)))
        for pair_id, data in db.execute("SELECT pair_id, data FROM two_view_geometries")
            if data is not None)
    db.commit()
    db.close()

    return keypoints, images_name, all_matches, inlier_matches


if __name__ == "__main__":
    example_usage()
