# type_studio.py

import threading
import logging
import datetime
import os
from xml.dom import minidom

from django.conf import settings
from ..utils import add_comment
from pod.video.models import Video, get_storage_path_video
from pod.video import encode
from django.template.defaultfilters import slugify
from pod.video.video_merge import start_video_merge

DEFAULT_RECORDER_TYPE_ID = getattr(settings, "DEFAULT_RECORDER_TYPE_ID", 1)

ENCODE_VIDEO = getattr(settings, "ENCODE_VIDEO", "start_encode")

STUDIO_ENCODE_VIDEOS = getattr(settings, "STUDIO_ENCODE_VIDEOS", start_video_merge)

log = logging.getLogger(__name__)


def process(recording):
    log.info("START PROCESS OF RECORDING %s" % recording)
    t = threading.Thread(target=encode_recording, args=[recording])
    t.setDaemon(True)
    t.start()


def save_basic_video(recording, video_src):
    # Save & encode one video corresponding to the recording without cut
    # We don't generate an intermediate video
    recorder = recording.recorder
    video = Video()
    # Video title corresponds to recording title
    video.title = recording.title
    video.owner = recording.user
    # Video type
    video.type = recorder.type
    # Video management
    storage_path = get_storage_path_video(video, os.path.basename(video_src))
    dt = str(datetime.datetime.now()).replace(":", "-")
    name, ext = os.path.splitext(os.path.basename(video_src))
    ext = ext.lower()
    video.video = os.path.join(
        os.path.dirname(storage_path), slugify(name) + "_" + dt.replace(" ", "_") + ext
    )
    # Move source file to destination
    os.makedirs(os.path.dirname(video.video.path), exist_ok=True)
    os.rename(video_src, video.video.path)
    video.save()

    # Add any additional owners
    video.additional_owners.add(*recorder.additional_users.all())
    # Private access (draft mode)
    video.is_draft = recorder.is_draft
    # Restricted access (possibly to groups or by password)
    video.is_restricted = recorder.is_restricted
    video.restrict_access_to_groups.add(*recorder.restrict_access_to_groups.all())
    video.password = recorder.password
    # Add the possible channels
    video.channel.add(*recorder.channel.all())
    # Add the possible themes
    video.theme.add(*recorder.theme.all())
    # Add any disciplines
    video.discipline.add(*recorder.discipline.all())
    # Language choice
    video.main_lang = recorder.main_lang
    # Cursus
    video.cursus = recorder.cursus
    # Tags
    video.tags = recorder.tags
    # Transcription
    if getattr(settings, "USE_TRANSCRIPTION", False):
        video.transcript = recorder.transcript
    # Licence
    video.licence = recorder.licence
    # Allow downloading
    video.allow_downloading = recorder.allow_downloading
    # Is 360
    video.is_360 = recorder.is_360
    # Disable comments
    video.disable_comment = recorder.disable_comment
    # Add sites
    video.sites.add(*recorder.sites.all())
    # Finally save
    video.save()

    encode_video = getattr(encode, ENCODE_VIDEO)
    encode_video(video.id)

    # Rename the XML file
    os.rename(recording.source_file, recording.source_file + "_treated")


def generate_intermediate_video(video_1, video_2, video_output):
    # We must generate an intermediate video (see video/studio.py)
    STUDIO_ENCODE_VIDEOS(video_1, video_2, video_output)


def encode_recording(recording):  # noqa: C901
    recording.comment = ""
    recording.save()
    add_comment(recording.id, "Start at %s\n--\n" % datetime.datetime.now())

    try:
        # Read the Pod XML file
        file_xml = open(recording.source_file, "r")
        text_xml = file_xml.read()
        # XML result to parse
        xmldoc = minidom.parseString(text_xml)
    except KeyError as e:
        add_comment(recording.id, "Error : %s" % e)
        return -1

    # Video file output : at the same directory than the XML file
    # And with the same name .mp4
    video_output = recording.source_file.replace(".xml", ".mp4")
    # Rename the XML file
    os.rename(recording.source_file, recording.source_file + "_treated")

    video_presenter_src = ""
    video_presenter_path = None
    video_presentation_src = ""
    video_presentation_path = None
    # Get informations from XML file
    if xmldoc.getElementsByTagName("video")[0].firstChild:
        video_presenter_src = xmldoc.getElementsByTagName("video")[0].firstChild.data
        video_presenter_path = os.path.join(
            settings.MEDIA_ROOT, 'opencast-files', video_presenter_src
        )

    if xmldoc.getElementsByTagName("video")[1].firstChild:
        video_presentation_src = xmldoc.getElementsByTagName("video")[1].firstChild.data
        video_presentation_path = os.path.join(
            settings.MEDIA_ROOT, 'opencast-files', video_presentation_src
        )

    # Informations for cut
    clip_begin = xmldoc.getElementsByTagName("cut")[0].getAttribute("clipBegin")
    clip_end = xmldoc.getElementsByTagName("cut")[0].getAttribute("clipEnd")

    # Management of the differents cases
    if not clip_begin and not clip_end and not (video_presenter_src and video_presentation_src):
        # Save & encode video : if possible, we don't  generate an intermediate video
        # If there is no cut, we can create directly a Pod video (if only one managed)
        if video_presenter_src and not video_presentation_src:
            # Save & encode presenter vide
            msg = "*** Management of basic video file (presenter) %s ***" % video_presenter_path
            add_comment(recording.id, msg)
            # We don't generate an intermediate video
            save_basic_video(recording, video_presenter_path)
        elif not video_presenter_src and video_presentation_src:
            # Save & encode presentation video
            msg = "*** Management of basic video file (presentation) %s ***" % video_presentation_path
            add_comment(recording.id, msg)
            # We don't generate an intermediate video
            save_basic_video(recording, video_presentation_path)
    else:
        # Cut is necessary ; we must generate an intermediate video
        msg = "*** Cut or merge is necessary : generate an intermediate video ***"
        add_comment(recording.id, msg)
        generate_intermediate_video(video_presenter_path, video_presentation_path, video_output)