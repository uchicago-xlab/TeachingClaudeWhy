- running on 8x H200; needed to export `NCCL_NVLS_ENABLE=0` (disaple NVLink SHARP) due to some kind of Runpod NVLink misconfiguration
  - According to Claude, this shouldn't have much of a slowdown on a small training job

