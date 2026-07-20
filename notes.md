- running on 8x H200; needed to export `NCCL_NVLS_ENABLE=0` (disaple NVLink SHARP) due to some kind of Runpod NVLink misconfiguration
  - According to Claude, this shouldn't have much of a slowdown on a small training job

- Flash attn with packing is pretty much mandatory for 8x H200
  - Runpod has absolutely fried driver versions. cuda needs to be updated to build FA3 against torch cu13 wheels, install `cuda-toolkit-13-3` **not cuda**
  - FA3 build takes a lot of storage, either have a really large root volume, or set `TMPDIR=/workspace/tmp` when running `uv sync`

