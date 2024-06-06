#!/usr/bin/env python3

# Copyright 2024 Jiatong Shi
#  Apache 2.0  (http://www.apache.org/licenses/LICENSE-2.0)

"""Scorer Interface for Speech Evaluation."""

import argparse
import logging

import librosa
import soundfile as sf
import yaml
from tqdm import tqdm


def get_parser() -> argparse.Namespace:
    """Get argument parser."""
    parser = argparse.ArgumentParser(description="Speech Evaluation Interface")
    parser.add_argument(
        "--pred",
        type=str,
        help="Wav.scp for generated waveforms.",
    )
    parser.add_argument(
        "--score_config", type=str, default=None, help="Configuration of Score Config"
    )
    parser.add_argument(
        "--gt",
        type=str,
        default=None,
        help="Wav.scp for ground truth waveforms.",
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Path of directory to write the results.",
    )
    parser.add_argument(
        "--use_gpu", type=bool, default=False, help="whether to use GPU if it can"
    )
    parser.add_argument(
        "--verbose",
        default=1,
        type=int,
        help="Verbosity level. Higher is more logging.",
    )
    return parser


def load_score_modules(score_config, use_gt=True, use_gpu=False):
    score_modules = {}
    for config in score_config:
        print(config, flush=True)
        if config["name"] == "mcd_f0":
            logging.info("Loading MCD & F0 evaluation...")
            from speech_evaluation import mcd_f0

            score_modules["mcd_f0"] = {
                "module": mcd_f0,
                "args": {
                    "f0min": config.get("f0min", 0),
                    "f0max": config.get("f0max", 24000),
                    "mcep_shift": config.get("mcep_shift", 5),
                    "mcep_fftl": config.get("mcep_fftl", 1024),
                    "mcep_dim": config.get("mcep_dim", 39),
                    "mcep_alpha": config.get("mcep_alpha", 0.466),
                    "seq_mismatch_tolerance": config.get("seq_mismatch_tolerance", 0.1),
                    "power_threshold": config.get("power_threshold", -20),
                    "dtw": config.get("dtw", False),
                },
            }
            logging.info("Initiate MCD & F0 evaluation successfully.")

        elif config["name"] == "signal_metric":
            if not use_gt:
                logging.warning(
                    "Cannot use signal metric because no gt audio is provided"
                )
                continue

            logging.info("Loading signal metric evaluation...")
            from speech_evaluation import signal_metric

            score_modules["signal_metric"] = {"module": signal_metric}
            logging.info("Initiate signal metric evaluation successfully.")

        elif config["name"] == "discrete_speech":
            if not use_gt:
                logging.warning(
                    "Cannot use discrete speech metric because no gt audio is provided"
                )
                continue

            logging.info("Loading discrete speech evaluation...")
            from speech_evaluation import (discrete_speech_metric,
                                           discrete_speech_setup)

            score_modules["discrete_speech"] = {
                "module": discrete_speech_metric,
                "args": {
                    "discrete_speech_predictors": discrete_speech_setup(use_gpu=use_gpu)
                },
            }
            logging.info("Initiate discrete speech evaluation successfully.")

        elif config["name"] == "pseudo_mos":
            logging.info("Loading pseudo MOS evaluation...")
            from speech_evaluation import pseudo_mos_metric, pseudo_mos_setup

            predictor_dict, predictor_fs = pseudo_mos_setup(
                use_gpu=use_gpu,
                predictor_types=config.get("predictor_types", ["utmos"]),
                predictor_args=config.get("predictor_args", {}),
            )
            score_modules["pseudo_mos"] = {
                "module": pseudo_mos_metric,
                "args": {
                    "predictor_dict": predictor_dict,
                    "predictor_fs": predictor_fs,
                    "use_gpu": use_gpu,
                },
            }
            logging.info("Initiate pseudo MOS evaluation successfully.")

        elif config["name"] == "pesq":
            if not use_gt:
                logging.warning(
                    "Cannot use pesq metric because no gt audio is provided"
                )
                continue

            logging.info("Loadding pesq evaluation...")
            from speech_evaluation import pesq_metric

            score_modules["pesq"] = {"module": pesq_metric}
            logging.info("Initiate pesq evaluation successfully.")

        elif config["name"] == "stoi":
            if not use_gt:
                logging.warning(
                    "Cannot use stoi metric because no gt audio is provided"
                )
                continue

            logging.info("Loading stoi evaluation...")
            from speech_evaluation import stoi_metric

            score_modules["stoi"] = {"module": stoi_metric}
            logging.info("Initiate stoi evaluation successfully.")

        elif config["name"] == "visqol":
            if not use_gt:
                logging.warning(
                    "Cannot use visqol metric because no gt audio is provided"
                )
                continue

            logging.info("Loading visqol evaluation...")
            from speech_evaluation import visqol_metric, visqol_setup

            api, fs = visqol_setup(model=config.get("model", "default"))
            score_modules["visqol"] = {
                "module": visqol_metric,
                "args": {"api": api, "api_fs": fs},
            }
            logging.info("Initiate visqol evaluation successfully.")

        elif config["name"] == "speaker":
            if not use_gt:
                logging.warning(
                    "Cannot use speaker metric because no gt audio is provided"
                )
                continue

            logging.info("Loading speaker evaluation...")
            from speech_evaluation import speaker_metric, speaker_model_setup

            spk_model = speaker_model_setup(
                model_tag=config.get("model_tag", "default"),
                model_path=config.get("model_path", None),
                model_config=config.get("model_config", None),
                use_gpu=use_gpu,
            )
            score_modules["speaker"] = {
                "module": speaker_metric,
                "args": {"model": spk_model},
            }
            logging.info("Initiate speaker evaluation successfully.")

    return score_modules


def use_score_modules(score_modules, gen_wav, gt_wav, gen_sr):
    utt_score = {}
    for key in score_modules.keys():
        if key == "mcd_f0":
            score = score_modules[key]["module"](
                gen_wav, gt_wav, gen_sr, **score_modules[key]["args"]
            )
        elif key == "signal_metric":
            score = score_modules[key]["module"](gen_wav, gt_wav)
        elif key == "discrete_speech":
            score = score_modules[key]["module"](
                score_modules[key]["args"]["discrete_speech_predictors"],
                gen_wav,
                gt_wav,
                gen_sr,
            )
        elif key == "pseudo_mos":
            score = score_modules[key]["module"](
                gen_wav, gen_sr, **score_modules[key]["args"]
            )
        elif key == "pesq":
            score = score_modules[key]["module"](gen_wav, gt_wav, gen_sr)
        elif key == "stoi":
            score = score_modules[key]["module"](gen_wav, gt_wav, gen_sr)
        elif key == "visqol":
            score = score_modules[key]["module"](
                score_modules[key]["args"]["api"],
                score_modules[key]["args"]["api_fs"],
                gen_wav,
                gt_wav,
                gen_sr,
            )
        elif key == "speaker":
            score = score_modules[key]["module"](
                score_modules[key]["args"]["model"], gen_wav, gt_wav, gen_sr
            )
        else:
            raise NotImplementedError(f"Not supported {key}")

        logging.info(f"Score for {key} is {score}")
        utt_score.update(score)
    return utt_score


def list_scoring(gen_files, score_modules, gt_files=None, output_file=None):
    if output_file is not None:
        f = open(output_file, "w", encoding="utf-8")

    score_info = []
    for key in tqdm(gen_files.keys()):
        gen_wav, gen_sr = sf.read(gen_files[key])
        if gen_wav.shape[0] / gen_sr < 0.25:
            logging.warning("audio {} (generated) is too short to be evaluated with pesq or stoi, skipping".format(key))
            continue
        assert key in gt_files.keys(), "key {} not found in ground truth files".format(
            key
        )
        if gt_files is not None:
            gt_wav, gt_sr = sf.read(gt_files[key])

            if "pesq" in score_modules.keys() or "stoi" in score_modules.keys():
                if gt_wav.shape[0] / gt_sr < 0.25:
                    logging.warning("audio {} (ground truth) is too short to be evaluated with pesq or stoi, skipping".format(key))
                    continue
        else:
            gt_wav = None

        if gen_sr > gt_sr:
            logging.warning(
                "Resampling the generated audio to match the ground truth audio"
            )
            gen_wav = librosa.resample(gen_wav, orig_sr=gen_sr, target_sr=gt_sr)
        elif gen_sr < gt_sr:
            logging.warning(
                "Resampling the ground truth audio to match the generated audio"
            )
            gt_wav = librosa.resample(gt_wav, orig_sr=gt_sr, target_sr=gen_sr)

        utt_score = {"key": key}

        utt_score.update(use_score_modules(score_modules, gen_wav, gt_wav, gen_sr))

        if output_file is not None:
            f.write(f"{utt_score}\n")
        score_info.append(utt_score)
    logging.info("Scoring completed and save score at {}".format(output_file))
    return score_info


def load_summary(score_info):
    summary = {}
    for key in score_info[0].keys():
        if key != "key":
            summary[key] = sum([score[key] for score in score_info]) / len(score_info)
    return summary


def main():
    args = get_parser().parse_args()

    # logging info
    if args.verbose > 1:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s",
        )
    elif args.verbose > 0:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s",
        )
    else:
        logging.basicConfig(
            level=logging.WARN,
            format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s",
        )
        logging.warning("Skip DEBUG/INFO messages")

    gen_files = {}
    # find files
    with open(args.pred) as f:
        for line in f.readlines():
            key, value = line.strip().split(maxsplit=1)
            if value.endswith("|"):
                raise ValueError("Not supported wav.scp format.")
            gen_files[key] = value

    # find reference file
    if args.gt is not None:
        gt_files = {}
        with open(args.gt) as f:
            for line in f.readlines():
                key, value = line.strip().split(maxsplit=1)
                if value.endswith("|"):
                    raise ValueError("Not supported wav.scp format.")
                gt_files[key] = value
    else:
        gt_files = None

    # Get and divide list
    if len(gen_files) == 0:
        raise FileNotFoundError("Not found any generated audio files.")
    if gt_files is not None and len(gen_files) > len(gt_files):
        raise ValueError(
            "#groundtruth files are less than #generated files "
            f"(#gen={len(gen_files)} vs. #gt={len(gt_files)}). "
            "Please check the groundtruth directory."
        )

    logging.info("The number of utterances = %d" % len(gen_files))

    with open(args.score_config, "r", encoding="utf-8") as f:
        score_config = yaml.full_load(f)

    score_modules = load_score_modules(
        score_config,
        use_gt=(True if gt_files is not None else False),
        use_gpu=args.use_gpu,
    )

    assert len(score_config) > 0, "no scoring function is provided"

    score_info = list_scoring(
        gen_files, score_modules, gt_files, output_file=args.output_file
    )
    logging.info("Summary: {}".format(load_summary(score_info)))


if __name__ == "__main__":
    main()
