import argparse
from moviepy import ImageClip, AudioFileClip, VideoFileClip, ColorClip, AudioClip, concatenate_videoclips
from openai import OpenAI
import os
from PIL import Image, ImageDraw, ImageFont

TEMP_AUDIO_PATH = "content/video_surfer/audio/temp_speech.mp3"
TEMP_IMAGE_PATH = "content/video_surfer/img/temp_text.png"

def image_to_video(text_file_path: str, duration: float = 5.0, output_path: str = "output.mp4", temp_image_path: str = TEMP_IMAGE_PATH) -> str:
    """Convert a text file to an image, then to an MP4 video with silent audio."""
    # Read text file
    with open(text_file_path, 'r') as file:
        text_content = file.read()
    
    # Create image from text
    width = 1920
    height = 1080
    background_color = (0, 0, 0)
    text_color = (255, 255, 255)
    
    # Create image and draw context
    img = Image.new('RGB', (width, height), background_color)
    draw = ImageDraw.Draw(img)
    
    font = ImageFont.truetype(font="content/video_surfer/img/Menlo.ttc", size=23)
    
    # Split text into lines (preserving whitespace)
    lines = text_content.splitlines()
    text_height = 50  # Starting height
    margin = 40
    
    # Draw each line
    for line in lines:
        draw.text((margin, text_height), line, font=font, fill=text_color)
        text_height += 35  # Increased line spacing for larger font
    
    # Save temporary image
    img.save(temp_image_path)
    
    # Create silent audio
    silent_clip = AudioClip(lambda t: 0, duration=duration)
    
    # Create video with silent audio
    clip = ImageClip(temp_image_path).with_duration(duration)
    clip = clip.with_audio(silent_clip)
    clip.write_videofile(output_path, fps=24)
    
    # Clean up
    # os.remove(temp_image_path)
    return output_path

def text_to_speech_video(text_file_path: str, output_path: str = "output.mp4", override_audio_path: bool = False) -> str:
    """Create a video with black background and TTS audio from text file."""
    # Read text file
    with open(text_file_path, 'r') as file:
        text_content = file.read()

    if override_audio_path or not os.path.exists(TEMP_AUDIO_PATH):
        # Generate TTS audio using OpenAI
        client = OpenAI()
        audio_response = client.audio.speech.create(
            model="tts-1",
            voice="ash",
            input=text_content,
            speed=1
        )
        
        # Save audio to temporary file
        audio_response.stream_to_file(TEMP_AUDIO_PATH)
    
    # Create black background video
    audio_clip = AudioFileClip(TEMP_AUDIO_PATH)
    duration = audio_clip.duration
    black_bg = ColorClip(size=(1920, 1080), color=(0, 0, 0)).with_duration(duration)
    
    # Combine audio and video
    final_clip = black_bg.with_audio(audio_clip)
    final_clip.write_videofile(output_path, fps=24)
    
    # Clean up temporary file
    # os.remove(temp_audio)
    return output_path

def image_with_tts_video(image_path: str, text_file_path: str, output_path: str = "output.mp4", override_audio_path: bool = False) -> str:
    """Create a video from image with TTS audio from text file."""

    if override_audio_path or not os.path.exists(TEMP_AUDIO_PATH):
        # Generate TTS audio
        with open(text_file_path, 'r') as file:
            text_content = file.read()
        
        client = OpenAI()
        audio_response = client.audio.speech.create(
            model="tts-1",
            voice="ash",
            input=text_content,
            speed=1
        )
        
        audio_response.stream_to_file(TEMP_AUDIO_PATH)
        
    # Create video from image with audio
    audio_clip = AudioFileClip(TEMP_AUDIO_PATH)
    image_clip = ImageClip(image_path).with_duration(audio_clip.duration)
    final_clip = image_clip.with_audio(audio_clip)
    final_clip.write_videofile(output_path, fps=24)
    
    # os.remove(temp_audio)
    return output_path

def insert_audio_segment(source_video_path: str,
                        insert_audio_path: str,
                        output_path: str = "output.mp4") -> str:
    """Insert an audio segment into the middle of a source video."""
    # Load all clips
    source_clip = VideoFileClip(source_video_path)
    insert_clip = AudioFileClip(insert_audio_path)
    pad_clip = None

    if insert_clip.duration > source_clip.duration:
        pad_clip = ColorClip(size=(1920, 1080), color=(0, 0, 0)).with_duration(insert_clip.duration - source_clip.duration)

    if pad_clip:
        final_clip = concatenate_videoclips([source_clip, pad_clip])
        final_clip = final_clip.with_audio(insert_clip)
    else:
        final_clip = source_clip.with_audio(insert_clip)

    final_clip.write_videofile(output_path, fps=24)

    return output_path

def insert_video_segment(source_video_path: str,
                        insert_video_path: str,
                        insert_time: float,
                        output_path: str = "output.mp4") -> str:
    """Insert an image+TTS video segment into the middle of a source video."""
    # Load all clips
    source_clip = VideoFileClip(source_video_path)
    insert_clip = VideoFileClip(insert_video_path)
    
    # Ensure insert_time doesn't exceed video duration
    insert_time = min(insert_time, source_clip.duration - 0.1)  # Leave 0.1s buffer
    
    # Split the source video
    part1 = source_clip.subclipped(0, insert_time)
    part2 = source_clip.subclipped(insert_time) if insert_time < source_clip.duration else None
    
    # Concatenate all parts
    if part2 is not None:
        final_clip = concatenate_videoclips([part1, insert_clip, part2])
    else:
        final_clip = concatenate_videoclips([part1, insert_clip])
    
    final_clip.write_videofile(output_path, fps=24)
    
    # Clean up
    source_clip.close()
    insert_clip.close()
    
    return output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", type=str, required=True)
    parser.add_argument("--image_path", type=str, required=False)
    parser.add_argument("--text_file_path", type=str, required=False)
    parser.add_argument("--duration", type=float, required=False)
    parser.add_argument("--source_video_path", type=str, required=False)
    parser.add_argument("--insert_video_path", type=str, required=False)
    parser.add_argument("--insert_time", type=float, required=False)
    parser.add_argument("--insert_audio_path", type=str, required=False)
    parser.add_argument("--output_path", type=str, required=True)
    parser.add_argument("--override_audio_path", type=bool, required=False)
    args = parser.parse_args()

    if args.mode == "image_to_video":
        if args.text_file_path is None:
            raise ValueError("text_file_path is required for image_to_video mode")
        if args.duration is None:
            raise ValueError("duration is required for image_to_video mode")
        if args.output_path is None:
            raise ValueError("output_path is required for image_to_video mode")
        
        image_to_video(args.text_file_path, args.duration, args.output_path)
        print(f"Video saved to {args.output_path}")

    elif args.mode == "text_to_speech_video":
        if args.text_file_path is None:
            raise ValueError("text_file_path is required for text_to_speech_video mode")
        if args.output_path is None:
            raise ValueError("output_path is required for text_to_speech_video mode")
        
        text_to_speech_video(args.text_file_path, args.output_path, args.override_audio_path)
        print(f"Video saved to {args.output_path}")

    elif args.mode == "image_with_tts_video":
        if args.image_path is None:
            raise ValueError("image_path is required for image_with_tts_video mode")
        if args.text_file_path is None:
            raise ValueError("text_file_path is required for image_with_tts_video mode")
        if args.output_path is None:
            raise ValueError("output_path is required for image_with_tts_video mode")
        
        image_with_tts_video(args.image_path, args.text_file_path, args.output_path, args.override_audio_path)
        print(f"Video saved to {args.output_path}")

    elif args.mode == "insert_video_segment":
        if args.source_video_path is None:
            raise ValueError("source_video_path is required for insert_video_segment mode")
        if args.insert_video_path is None:
            raise ValueError("insert_video_path is required for insert_video_segment mode")
        if args.insert_time is None:
            raise ValueError("insert_time is required for insert_video_segment mode")
        if args.output_path is None:
            raise ValueError("output_path is required for insert_video_segment mode")
        
        insert_video_segment(args.source_video_path, args.insert_video_path, args.insert_time, args.output_path)
        print(f"Video saved to {args.output_path}")

    elif args.mode == "insert_audio_segment":
        if args.source_video_path is None:
            raise ValueError("source_video_path is required for insert_audio_segment mode")
        if args.insert_audio_path is None:
            raise ValueError("insert_audio_path is required for insert_audio_segment mode")
        if args.output_path is None:
            raise ValueError("output_path is required for insert_audio_segment mode")
        
        insert_audio_segment(args.source_video_path, args.insert_audio_path, args.output_path)
        print(f"Video saved to {args.output_path}")
