#!/usr/bin/env python3
"""
mov_compress.py
───────────────
Réduit la taille d'un screen recording MOV sans toucher à la résolution.

Trois modes :
  fast      — ffmpeg mpdecimate natif, zéro Python, le plus rapide (défaut)
  adaptive  — Python single-pass + pipe ffmpeg, contrôle fin du threshold
  fixed     — ffmpeg fps filter, simple et rapide

Dépendances : ffmpeg (système), opencv-python + numpy (mode adaptive seulement)
Install     : sudo apt install ffmpeg
              pip install opencv-python numpy  # seulement pour --mode adaptive

Utilisation :
  # Rapide : mpdecimate auto (recommandé)
  python3 mov_compress.py input.mov output.mov

  # Ajuster la sensibilité (0=très sensible … 100=peu sensible)
  python3 mov_compress.py input.mov output.mov --sensitivity 30

  # FPS fixe (encore plus rapide)
  python3 mov_compress.py input.mov output.mov --mode fixed --fps 10

  # Contrôle fin Python (plus lent mais threshold précis)
  python3 mov_compress.py input.mov output.mov --mode adaptive --threshold 0.015

  # Conserver l'audio
  python3 mov_compress.py input.mov output.mov --keep-audio
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile


# ── Utilitaires ───────────────────────────────────────────────────────────────

def file_mb(path: str) -> float:
    return os.path.getsize(path) / 1024 / 1024


def print_sep(width=56):
    print("─" * width)


def probe_video(input_file: str) -> dict:
    """Retourne fps, width, height, duration, has_audio."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
            "-show_entries", "format=duration",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1",
            input_file,
        ],
        capture_output=True, text=True,
    )
    info: dict = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()

    # FPS
    rfr = info.get("r_frame_rate", "30/1")
    num, den = map(int, rfr.split("/"))
    info["fps"] = num / den if den else 30.0

    # Durée
    info["duration"] = float(info.get("duration", 0))

    # Audio
    audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type",
         "-of", "default=noprint_wrappers=1:nokey=1", input_file],
        capture_output=True, text=True,
    )
    info["has_audio"] = "audio" in audio.stdout

    return info


def _print_result(input_file: str, output_file: str):
    orig_mb = file_mb(input_file)
    new_mb  = file_mb(output_file)
    gain    = (1 - new_mb / orig_mb) * 100
    print_sep()
    print(f"  Terminé !")
    print(f"  Avant   : {orig_mb:.1f} Mo")
    print(f"  Après   : {new_mb:.1f} Mo")
    print(f"  Gain    : {gain:.0f}%")
    print_sep()


def _audio_opts(keep_audio: bool, has_audio: bool) -> list[str]:
    if keep_audio and has_audio:
        return ["-c:a", "aac", "-b:a", "96k"]
    return ["-an"]


# ── Mode fast : ffmpeg mpdecimate (défaut) ────────────────────────────────────

def compress_fast(
    input_file: str,
    output_file: str,
    max_fps: int = 10,
    sensitivity: int = 10,
    crf: int = 23,
    keep_audio: bool = False,
):
    """
    Compression via le filtre ffmpeg `mpdecimate`.
    Supprime les frames quasi-identiques sans aucune lecture Python.
    Single-pass, pas de fichiers temporaires.

    sensitivity : 0 = très sensible (retient les petits mouvements)
                  50 = défaut équilibré
                  100 = peu sensible (retient seulement les grands changements)
    """
    info = probe_video(input_file)
    w, h  = info.get("width", "?"), info.get("height", "?")
    fps   = info["fps"]
    dur   = info["duration"]

    # mpdecimate : hi et lo sont des MAD par bloc (64×64).
    # Valeurs ffmpeg : hi=64*12=768, lo=64*5=320 (défauts).
    # On les scale selon sensitivity (0–100).
    hi = int(64 * (2 + sensitivity * 0.3))   # 128 … 2048
    lo = int(64 * (1 + sensitivity * 0.15))  # 64  … 1024

    vf = f"mpdecimate=hi={hi}:lo={lo}:frac=0.33,setpts=N/FRAME_RATE/TB,fps={max_fps}"

    print_sep()
    print(f"  Source      : {input_file}")
    print(f"  Taille      : {file_mb(input_file):.1f} Mo")
    print(f"  Vidéo       : {w}×{h} · {fps:.1f} fps · {dur:.0f}s")
    print(f"  Mode        : fast (mpdecimate) · max {max_fps} fps · sensitivity={sensitivity} · crf={crf}")
    print_sep()

    cmd = [
        "ffmpeg", "-y",
        "-i", input_file,
        "-vf", vf,
        "-vcodec", "libx264",
        "-crf", str(crf),
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        *_audio_opts(keep_audio, info["has_audio"]),
        output_file,
    ]

    print("  Encodage ffmpeg (mpdecimate)...")
    try:
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            print("ERREUR ffmpeg :")
            print(proc.stderr.decode(errors="replace")[-2000:])
            sys.exit(1)
    except FileNotFoundError:
        print("Erreur : ffmpeg introuvable. Installez-le avec : sudo apt install ffmpeg")
        sys.exit(1)

    _print_result(input_file, output_file)


# ── Mode fixed : fps filter ffmpeg ────────────────────────────────────────────

def compress_fixed(
    input_file: str,
    output_file: str,
    target_fps: int = 10,
    crf: int = 23,
    keep_audio: bool = False,
):
    """FPS fixe via ffmpeg. Simple, rapide, bon pour contenus uniformes."""
    info = probe_video(input_file)
    w, h = info.get("width", "?"), info.get("height", "?")
    fps  = info["fps"]

    print_sep()
    print(f"  Source  : {input_file}")
    print(f"  Taille  : {file_mb(input_file):.1f} Mo")
    print(f"  Vidéo   : {w}×{h} · {fps:.1f} fps · {info['duration']:.0f}s")
    print(f"  Mode    : fixed → {target_fps} fps · crf={crf}")
    print_sep()

    cmd = [
        "ffmpeg", "-y",
        "-i", input_file,
        "-vf", f"fps={target_fps}",
        "-vcodec", "libx264",
        "-crf", str(crf),
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        *_audio_opts(keep_audio, info["has_audio"]),
        output_file,
    ]

    print("  Encodage ffmpeg...")
    try:
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            print("ERREUR ffmpeg :")
            print(proc.stderr.decode(errors="replace")[-2000:])
            sys.exit(1)
    except FileNotFoundError:
        print("Erreur : ffmpeg introuvable.")
        sys.exit(1)

    _print_result(input_file, output_file)


# ── Mode adaptive : Python single-pass + pipe ffmpeg ─────────────────────────

def compress_adaptive(
    input_file: str,
    output_file: str,
    min_fps: float = 1.0,
    max_fps: float = 10.0,
    motion_threshold: float = 0.015,
    crf: int = 23,
    keep_audio: bool = False,
):
    """
    Compression adaptative Python.
    Single-pass : analyse + écriture sur disque simultanées (mémoire O(1) en frames).
    Plus lent que le mode fast mais permet un contrôle précis du threshold.

    Dépendances : pip install opencv-python numpy
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("Erreur : opencv-python et numpy requis pour le mode adaptive.")
        print("  pip install opencv-python numpy")
        sys.exit(1)

    cap = cv2.VideoCapture(input_file)
    if not cap.isOpened():
        raise FileNotFoundError(f"Impossible d'ouvrir : {input_file}")

    orig_fps   = cap.get(cv2.CAP_PROP_FPS) or 30
    width      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total      = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_s = total / orig_fps

    min_interval = 1.0 / max_fps
    max_interval = 1.0 / min_fps
    cmp_w = min(width, 320)
    cmp_h = min(height, 180)

    info = probe_video(input_file)

    print_sep()
    print(f"  Source   : {input_file}")
    print(f"  Taille   : {file_mb(input_file):.1f} Mo")
    print(f"  Vidéo    : {width}×{height} · {orig_fps:.1f} fps · {total} frames · {duration_s:.1f}s")
    print(f"  Mode     : adaptive {min_fps}–{max_fps} fps · threshold={motion_threshold} · crf={crf}")
    print_sep()

    tmp = tempfile.mkdtemp(prefix="mov_compress_")
    try:
        concat_path = os.path.join(tmp, "concat.txt")
        concat_lines: list[str] = []

        # Single-pass : analyse + écriture sur disque immédiate
        # Aucune frame BGR n'est gardée en mémoire entre les itérations
        last_kept_time = -999.0
        last_gray: "np.ndarray | None" = None
        frame_idx   = 0
        file_counter = 0
        img_paths: list[tuple[str, float]] = []  # (path, ts)

        print("  Analyse + extraction (single-pass)...")
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            ts = frame_idx / orig_fps
            dt = ts - last_kept_time
            gray = cv2.resize(
                cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                (cmp_w, cmp_h),
            ).astype(np.float32) / 255.0

            if last_gray is None:
                keep = True
            elif dt >= max_interval:
                keep = True
            elif dt >= min_interval:
                keep = bool(np.mean(np.abs(gray - last_gray)) > motion_threshold)
            else:
                keep = False

            if keep:
                img_path = os.path.join(tmp, f"f{file_counter:07d}.jpg")
                cv2.imwrite(img_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                img_paths.append((img_path, ts))
                file_counter += 1
                last_kept_time = ts
                last_gray = gray

            frame_idx += 1
            if frame_idx % 1000 == 0:
                pct = frame_idx / total * 100
                print(f"  Analyse  : {pct:5.1f}%  —  {file_counter} frames retenues...")

        cap.release()

        kept_pct      = file_counter / total * 100 if total else 0
        effective_fps = file_counter / duration_s if duration_s else 0
        print(f"\n  → {file_counter}/{total} frames ({kept_pct:.1f}%) · FPS moyen : {effective_fps:.2f}")

        # Construire le concat
        for i, (img_path, ts) in enumerate(img_paths):
            duration = (img_paths[i + 1][1] - ts) if i < len(img_paths) - 1 else max_interval
            concat_lines.append(f"file '{img_path}'\nduration {duration:.6f}\n")
        with open(concat_path, "w") as fh:
            fh.writelines(concat_lines)

        print("\n  Encodage ffmpeg...")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_path,
        ]
        if keep_audio and info["has_audio"]:
            cmd += ["-i", input_file, "-map", "0:v", "-map", "1:a",
                    "-c:a", "aac", "-b:a", "96k"]
        else:
            cmd += ["-an"]
        cmd += [
            "-vcodec", "libx264",
            "-crf", str(crf),
            "-preset", "slow",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_file,
        ]

        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            print("ERREUR ffmpeg :")
            print(proc.stderr.decode(errors="replace")[-2000:])
            sys.exit(1)

    finally:
        shutil.rmtree(tmp)

    _print_result(input_file, output_file)


# ── Calibrage threshold (mode adaptive) ──────────────────────────────────────

def calibrate_threshold(input_file: str, sample_seconds: float = 10.0) -> float:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0.015

    cap = cv2.VideoCapture(input_file)
    orig_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    max_frames = int(orig_fps * sample_seconds)
    cmp_w, cmp_h = 320, 180
    diffs = []
    last_gray = None

    for _ in range(max_frames):
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.resize(
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
            (cmp_w, cmp_h),
        ).astype(np.float32) / 255.0
        if last_gray is not None:
            diffs.append(float(np.mean(np.abs(gray - last_gray))))
        last_gray = gray
    cap.release()

    if not diffs:
        return 0.015
    threshold = float(np.percentile(diffs, 75))
    print(f"  Calibrage : médiane={float(np.median(diffs)):.4f} · p75={threshold:.4f}")
    return round(threshold, 4)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Compresse un screen recording MOV par réduction de FPS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python3 mov_compress.py capture.mov out.mov                    # fast, défaut
  python3 mov_compress.py capture.mov out.mov --sensitivity 30   # moins sensible
  python3 mov_compress.py capture.mov out.mov --mode fixed --fps 10
  python3 mov_compress.py capture.mov out.mov --mode adaptive --calibrate
  python3 mov_compress.py capture.mov out.mov --crf 28 --keep-audio
        """,
    )

    parser.add_argument("input",  help="Fichier MOV source")
    parser.add_argument("output", help="Fichier de sortie (MOV ou MP4)")

    parser.add_argument(
        "--mode", choices=["fast", "fixed", "adaptive"], default="fast",
        help="Mode de compression (défaut: fast)",
    )

    # Mode fast
    parser.add_argument("--sensitivity", type=int, default=10, metavar="0-100",
                        help="Sensibilité mpdecimate 0=max…100=min (défaut: 10)")

    # Mode adaptive
    parser.add_argument("--threshold", type=float, default=None,
                        help="Seuil mouvement 0.005–0.050 (défaut: auto)")
    parser.add_argument("--calibrate", action="store_true",
                        help="Calibrer le seuil automatiquement (mode adaptive)")
    parser.add_argument("--min-fps", type=float, default=1,
                        help="FPS plancher (défaut: 1)")

    # Commun fast + adaptive + fixed
    parser.add_argument("--max-fps", type=int, default=10,
                        help="FPS plafond / FPS cible en mode fixed (défaut: 10)")

    # Commun tous modes
    parser.add_argument("--crf", type=int, default=23,
                        help="Qualité x264 : 18=max, 23=défaut, 28=compact")
    parser.add_argument("--keep-audio", action="store_true",
                        help="Conserver la piste audio si présente")

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Erreur : fichier introuvable — {args.input}", file=sys.stderr)
        sys.exit(1)

    if args.mode == "fast":
        compress_fast(
            input_file=args.input,
            output_file=args.output,
            max_fps=args.max_fps,
            sensitivity=max(0, min(100, args.sensitivity)),
            crf=args.crf,
            keep_audio=args.keep_audio,
        )

    elif args.mode == "fixed":
        compress_fixed(
            input_file=args.input,
            output_file=args.output,
            target_fps=args.max_fps,
            crf=args.crf,
            keep_audio=args.keep_audio,
        )

    else:  # adaptive
        threshold = args.threshold
        if threshold is None or args.calibrate:
            print("Calibrage automatique du seuil...")
            threshold = calibrate_threshold(args.input)
            print(f"  Seuil retenu : {threshold}\n")

        compress_adaptive(
            input_file=args.input,
            output_file=args.output,
            min_fps=args.min_fps,
            max_fps=args.max_fps,
            motion_threshold=threshold,
            crf=args.crf,
            keep_audio=args.keep_audio,
        )


if __name__ == "__main__":
    main()
