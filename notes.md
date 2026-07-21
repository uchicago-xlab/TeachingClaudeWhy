- running on 8x H200; needed to export `NCCL_NVLS_ENABLE=0` (disaple NVLink SHARP) due to some kind of Runpod NVLink misconfiguration
  - According to Claude, this shouldn't have much of a slowdown on a small training job

- Flash attn with packing is pretty much mandatory for 8x H200
  - Runpod has absolutely fried driver versions. cuda needs to be updated to build FA3 against torch cu13 wheels, install `cuda-toolkit-13-3` **not cuda**
  - FA3 build takes a lot of storage, either have a really large root volume, or set `TMPDIR=/workspace/tmp` when running `uv sync`
  - Also FA3 does not build without nvcc (or without Nvidia GPU I think) so make sure to download the lock file from the runpod pod
  - from 5hr 40m to about 1hr 30m

- Enabled liger kernel otherwise cuda cache keeps OOMing (warning, not error, but slow)
  - 8x H200 seems stable with current hyperparameters and optimizations

- One checkpoint is about 500G
