#!/bin/bash

# Generate a static image video from a text file
python agents/video_surfer/generate_inputs.py --mode image_to_video --text_file_path agents/video_surfer/img/jb_img.txt --output_path agents/video_surfer/video/jb_img.mp4 --duration 5

# Generate a only-audio video from a text file
python agents/video_surfer/generate_inputs.py --mode text_to_speech_video --text_file_path agents/video_surfer/audio/jb_audio.txt --output_path agents/video_surfer/video/jb_audio.mp4

# Generate a video with an image and audio from a text file
python agents/video_surfer/generate_inputs.py --mode image_with_tts_video --image_path agents/video_surfer/img/temp_text.png --text_file_path agents/video_surfer/audio/jb_audio.txt --output_path agents/video_surfer/video/jb_img_audio.mp4

# Insert audio into a video
python agents/video_surfer/generate_inputs.py --mode insert_audio_segment --source_video_path agents/video_surfer/video/original_video.mp4 --insert_audio_path agents/video_surfer/audio/temp_speech.mp3 --output_path agents/video_surfer/video/original_video_temp_audio.mp4

# Insert image + audio into a video
# source for insertion: https://www.pexels.com/video/german-shepherd-chilling-on-snowy-weather-6209964/
python agents/video_surfer/generate_inputs.py --mode insert_video_segment --source_video_path agents/video_surfer/video/original_video.mp4 --insert_video_path agents/video_surfer/video/jb_img_audio.mp4 --insert_time 5 --output_path agents/video_surfer/video/jb_img_audio_inserted.mp4