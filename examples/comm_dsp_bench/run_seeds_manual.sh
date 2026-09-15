#!/bin/zsh
# 5 seeds × 混合模式 × 40 迭代（manual 模式统计验证）
BENCH=/Users/chengzhy/verievolve/examples/comm_dsp_bench
PY=/Users/chengzhy/verievolve/.venv/bin/python
cd /Users/chengzhy/verievolve
export COMMDSP_TASK=cordic_sincos
for seed in 0 1 2 3 4; do
  out=$BENCH/experiments/cordic_sincos_40/seed_$seed
  rm -rf $out && mkdir -p $out
  sed "s/random_seed: 42/random_seed: $seed/" $BENCH/config_seeds_manual.yaml > $out/config.yaml
  echo "===== seed $seed start: $(date) ====="
  $PY openevolve-run.py \
      $BENCH/tasks/cordic_sincos/initial_program.v \
      $BENCH/evaluator.py \
      --config $out/config.yaml \
      --output $out \
      --iterations 40 > /dev/null 2>&1 &
  evo=$!
  $PY $BENCH/ablation_responder.py --group C \
      --queue $out/manual_tasks_queue \
      --max-rounds 60 --idle-exit 45 > $out/responder.log 2>&1 &
  resp=$!
  wait $evo
  kill $resp 2>/dev/null
  echo "===== seed $seed done: $(date) ====="
done
echo "ALL SEEDS COMPLETE"
