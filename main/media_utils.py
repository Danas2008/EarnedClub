import os
import subprocess
import tempfile
import uuid
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile

from .supabase_storage import build_object_path, delete_object, get_public_object_url, upload_content

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None
    ImageOps = None


PROFILE_IMAGE_SIZE = 720
RESAMPLING_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None) if Image else None


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def process_profile_image(uploaded_file, crop_x=None, crop_y=None, crop_size=None):
    if not uploaded_file or Image is None or ImageOps is None:
        return uploaded_file

    uploaded_file.seek(0)
    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image).convert("RGB")

    width, height = image.size
    crop_size_value = _safe_float(crop_size, default=min(width, height))
    crop_size_value = max(1.0, min(crop_size_value, width, height))

    left = max(0.0, min(_safe_float(crop_x), width - crop_size_value))
    top = max(0.0, min(_safe_float(crop_y), height - crop_size_value))
    right = left + crop_size_value
    bottom = top + crop_size_value

    if crop_size in (None, "", "0", 0):
        square_size = min(width, height)
        left = (width - square_size) / 2
        top = (height - square_size) / 2
        right = left + square_size
        bottom = top + square_size

    cropped = image.crop((int(left), int(top), int(right), int(bottom)))
    resized = cropped.resize((PROFILE_IMAGE_SIZE, PROFILE_IMAGE_SIZE), RESAMPLING_LANCZOS or Image.BICUBIC)

    output = BytesIO()
    resized.save(output, format="JPEG", quality=82, optimize=True, progressive=True)
    output.seek(0)

    stem = Path(getattr(uploaded_file, "name", "profile")).stem or "profile"
    return ContentFile(output.read(), name=f"{stem}-{uuid.uuid4().hex[:8]}.jpg")


def process_submission_video(uploaded_file):
    if not uploaded_file:
        return uploaded_file

    suffix = Path(getattr(uploaded_file, "name", "")).suffix or ".mp4"
    uploaded_file.seek(0)

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as source_file:
        for chunk in uploaded_file.chunks():
            source_file.write(chunk)
        source_path = source_file.name

    output_path = f"{source_path}-compressed.mp4"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        source_path,
        "-vf",
        "scale='min(854,iw)':'min(480,ih)':force_original_aspect_ratio=decrease",
        "-r",
        "24",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "32",
        "-movflags",
        "+faststart",
        "-an",
        output_path,
    ]

    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=180)
        if result.returncode != 0 or not os.path.exists(output_path):
            uploaded_file.seek(0)
            return uploaded_file

        with open(output_path, "rb") as output_file:
            return ContentFile(
                output_file.read(),
                name=f"{Path(getattr(uploaded_file, 'name', 'submission')).stem}-{uuid.uuid4().hex[:8]}.mp4",
            )
    finally:
        for path in (source_path, output_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


def store_profile_image(profile, uploaded_file, crop_x=None, crop_y=None, crop_size=None):
    processed_file = process_profile_image(uploaded_file, crop_x=crop_x, crop_y=crop_y, crop_size=crop_size)
    processed_file.seek(0)
    content = processed_file.read()
    object_path = build_object_path(f"profile-{profile.user_id}", getattr(processed_file, "name", "profile.jpg"))

    if upload_content(settings.SUPABASE_PROFILE_BUCKET, object_path, content, content_type="image/jpeg"):
        if getattr(profile, "profile_storage_path", ""):
            delete_object(settings.SUPABASE_PROFILE_BUCKET, profile.profile_storage_path)
        return {
            "storage_path": object_path,
            "public_url": get_public_object_url(settings.SUPABASE_PROFILE_BUCKET, object_path),
            "local_file": None,
        }

    processed_file.seek(0)
    return {"storage_path": "", "public_url": "", "local_file": processed_file}


def store_submission_video(submission, uploaded_file):
    processed_file = process_submission_video(uploaded_file)
    processed_file.seek(0)
    content = processed_file.read()
    object_path = build_object_path(
        f"submission-{submission.user_id or submission.pk or 'anon'}",
        getattr(processed_file, "name", "submission.mp4"),
    )

    if upload_content(settings.SUPABASE_SUBMISSION_BUCKET, object_path, content, content_type="video/mp4"):
        if getattr(submission, "video_storage_path", ""):
            delete_object(settings.SUPABASE_SUBMISSION_BUCKET, submission.video_storage_path)
        return {"storage_path": object_path, "local_file": None}

    processed_file.seek(0)
    return {"storage_path": "", "local_file": processed_file}
