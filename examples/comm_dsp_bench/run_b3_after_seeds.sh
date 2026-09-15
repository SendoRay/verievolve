#!/bin/zsh
# B3 scalar-boolean 基线进化（等 5 seeds 完成后自动执行）
BENCH=/Users/chengzhy/verievolve/examples/comm_dsp_bench
PY=/Users/chengzhy/verievolve/.venv/bin/python
cd /Users/chengzhy/verievolve
export COMMDSP_TASK=cordic_sincos

# 等 seeds driver 结束
while pgrep -f "run_seeds_manual.sh" > /dev/null; do sleep 60; done
echo "seeds done, starting B3: $(date)"

out=$BENCH/output_b3_scalar
rm -rf $out && mkdir -p $out
$PY openevolve-run.py \
    $BENCH/tasks/cordic_sincos/initial_program.v \
    $BENCH/evaluator_scalar.py \
    --config $BENCH/config_b3_scalar.yaml \
    --output $out \
    --iterations 40 > /dev/null 2>&1 &
evo=$!
$PY $BENCH/ablation_responder.py --group C \
    --queue $out/manual_tasks_queue \
    --max-rounds 60 --idle-exit 45 > $out/responder.log 2>&1 &
resp=$!
wait $evo
kill $resp 2>/dev/null
echo "B3 COMPLETE: $(date)"
