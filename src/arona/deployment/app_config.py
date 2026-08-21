"""Generate the fixed MVP application configuration headers."""

from __future__ import annotations

from pathlib import Path

from arona.contracts.v1 import DeploymentApplication

FOOD101_CLASSES = (
    "apple_pie",
    "baby_back_ribs",
    "baklava",
    "beef_carpaccio",
    "beef_tartare",
    "beet_salad",
    "beignets",
    "bibimbap",
    "bread_pudding",
    "breakfast_burrito",
    "bruschetta",
    "caesar_salad",
    "cannoli",
    "caprese_salad",
    "carrot_cake",
    "ceviche",
    "cheesecake",
    "cheese_plate",
    "chicken_curry",
    "chicken_quesadilla",
    "chicken_wings",
    "chocolate_cake",
    "chocolate_mousse",
    "churros",
    "clam_chowder",
    "club_sandwich",
    "crab_cakes",
    "creme_brulee",
    "croque_madame",
    "cup_cakes",
    "deviled_eggs",
    "donuts",
    "dumplings",
    "edamame",
    "eggs_benedict",
    "escargots",
    "falafel",
    "filet_mignon",
    "fish_and_chips",
    "foie_gras",
    "french_fries",
    "french_onion_soup",
    "french_toast",
    "fried_calamari",
    "fried_rice",
    "frozen_yogurt",
    "garlic_bread",
    "gnocchi",
    "greek_salad",
    "grilled_cheese_sandwich",
    "grilled_salmon",
    "guacamole",
    "gyoza",
    "hamburger",
    "hot_and_sour_soup",
    "hot_dog",
    "huevos_rancheros",
    "hummus",
    "ice_cream",
    "lasagna",
    "lobster_bisque",
    "lobster_roll_sandwich",
    "macaroni_and_cheese",
    "macarons",
    "miso_soup",
    "mussels",
    "nachos",
    "omelette",
    "onion_rings",
    "oysters",
    "pad_thai",
    "paella",
    "pancakes",
    "panna_cotta",
    "peking_duck",
    "pho",
    "pizza",
    "pork_chop",
    "poutine",
    "prime_rib",
    "pulled_pork_sandwich",
    "ramen",
    "ravioli",
    "red_velvet_cake",
    "risotto",
    "samosa",
    "sashimi",
    "scallops",
    "seaweed_salad",
    "shrimp_and_grits",
    "spaghetti_bolognese",
    "spaghetti_carbonara",
    "spring_rolls",
    "steak",
    "strawberry_shortcake",
    "sushi",
    "tacos",
    "takoyaki",
    "tiramisu",
    "tuna_tartare",
    "waffles",
)


def configure_mvp_application(
    application: DeploymentApplication,
    application_directory: Path,
) -> Path:
    """Write the model-specific app_config.h for one of the two fixed MVP models."""

    config_path = application_directory / "Inc/app_config.h"
    if not config_path.parent.is_dir():
        raise ValueError(f"Official application include directory is missing: {config_path.parent}")
    content = (
        _image_classification_config()
        if application == DeploymentApplication.IMAGE_CLASSIFICATION
        else _object_detection_config()
    )
    config_path.write_text(content, encoding="utf-8")
    return config_path


def _image_classification_config() -> str:
    return f"""#ifndef APP_CONFIG
#define APP_CONFIG

#define USE_DCACHE
#define CAMERA_FLIP CMW_MIRRORFLIP_NONE

#define ASPECT_RATIO_CROP       (1)
#define ASPECT_RATIO_FIT        (2)
#define ASPECT_RATIO_FULLSCREEN (3)
#define ASPECT_RATIO_MODE ASPECT_RATIO_CROP

#define COLOR_BGR (0)
#define COLOR_RGB (1)
#define COLOR_MODE COLOR_RGB

#define NB_CLASSES {len(FOOD101_CLASSES)}
{_classes_macro(FOOD101_CLASSES)}

#define WELCOME_MSG_1 "MobileNetV2 0.35 Food-101 128x128"
#define WELCOME_MSG_2 ((char *[2]) {{"ARONA / Neural-ART", "ONNX QDQ"}})

#endif
"""


def _object_detection_config() -> str:
    return f"""#ifndef APP_CONFIG
#define APP_CONFIG

#include "arm_math.h"

#define USE_DCACHE
#define CAMERA_FLIP CMW_MIRRORFLIP_NONE

#define ASPECT_RATIO_CROP       (1)
#define ASPECT_RATIO_FIT        (2)
#define ASPECT_RATIO_FULLSCREEN (3)
#define ASPECT_RATIO_MODE ASPECT_RATIO_CROP

#define POSTPROCESS_TYPE POSTPROCESS_OD_YOLO_V8_UI

#define COLOR_BGR (0)
#define COLOR_RGB (1)
#define COLOR_MODE COLOR_RGB

#define NB_CLASSES 1
{_classes_macro(("person",))}

#define AI_OD_YOLOV8_PP_NB_CLASSES      (1)
#define AI_OD_YOLOV8_PP_TOTAL_BOXES     (1344)
#define AI_OD_YOLOV8_PP_CONF_THRESHOLD  (0.5f)
#define AI_OD_YOLOV8_PP_IOU_THRESHOLD   (0.5f)
#define AI_OD_YOLOV8_PP_MAX_BOXES_LIMIT (10)

#define WELCOME_MSG_1 "YOLO26n COCO-Person 256x256"
#define WELCOME_MSG_2 ((char *[2]) {{"ARONA / Neural-ART", "ONNX QDQ Int8"}})

#endif
"""


def _classes_macro(classes: tuple[str, ...]) -> str:
    lines = ["#define CLASSES_TABLE const char *classes_table[NB_CLASSES] = {\\"]
    for index, name in enumerate(classes):
        suffix = "}"
        if index < len(classes) - 1:
            suffix = ",\\"
        lines.append(f'    "{name}"{suffix}')
    return "\n".join(lines)
