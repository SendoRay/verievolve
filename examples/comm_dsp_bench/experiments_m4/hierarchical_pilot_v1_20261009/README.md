# M4 hierarchical action proposer formal

DeepSeek selects only a generic hardware action. A frozen executor expands it to a legal unvisited typed neighbor. Repeated valid actions remain valid while another neighbor exists; invalid or exhausted actions use a recorded least-used deterministic fallback without spending an extra evaluation.

The non-LLM comparator is UCB1 over the same actions and uses the same expansion rule. Every cell has exactly eight new-candidate evaluations. FIR and NCO terminal truth and strict Nangate45 area identities are inherited unchanged from their formal v2 artifacts; no RTL generation or synthesis is performed here.

## FIR

- `ucb1_action:boolean`: 3/3 complete; [0.3862070994139518, 0.3862070994139518, 0.3862070994139518]
- `ucb1_action:numerical`: 3/3 complete; [0.3862070994139518, 0.3862070994139518, 0.3862070994139518]
- `deepseek_hierarchical_action:boolean`: 3/3 complete; [0.5212938995155353, 0.5212938995155353, 0.5212938995155353]
- `deepseek_hierarchical_action:numerical`: 3/3 complete; [0.47910784535154327, 0.47910784535154327, 0.47910784535154327]

Interaction records: [{'seed': 20261031, 'value': -0.042186054163992015}, {'seed': 20261032, 'value': -0.042186054163992015}, {'seed': 20261033, 'value': -0.042186054163992015}]; mean -0.042186054163992015.
LLM accounting: {'recorded_calls': 48, 'api_ok_calls': 47, 'repeated_action_proposals': 29, 'fallback_expansions': 1, 'invalid_or_failed_action_calls': 1, 'exhausted_action_calls': 0, 'reported_input_tokens': 27727, 'reported_output_tokens': 4151, 'reported_cache_tokens': 4480, 'estimated_cost_usd_for_reported_usage': 0.01198218, 'recorded_call_elapsed_seconds': 76.55808783334214}.

## NCO

- `ucb1_action:boolean`: 3/3 complete; [0.7581126404708671, 0.7581126404708671, 0.7581126404708671]
- `ucb1_action:numerical`: 3/3 complete; [0.7581126404708671, 0.7581126404708671, 0.7581126404708671]
- `deepseek_hierarchical_action:boolean`: 3/3 complete; [0.7571006724609617, 0.7576031719537616, 0.7571006724609617]
- `deepseek_hierarchical_action:numerical`: 3/3 complete; [0.7463887759133787, 0.7581126404708671, 0.745696209756135]

Interaction records: [{'seed': 20261021, 'value': -0.010711896547582977}, {'seed': 20261022, 'value': 0.000509468517105538}, {'seed': 20261023, 'value': -0.011404462704826646}]; mean -0.007202296911768029.
LLM accounting: {'recorded_calls': 48, 'api_ok_calls': 48, 'repeated_action_proposals': 18, 'fallback_expansions': 0, 'invalid_or_failed_action_calls': 0, 'exhausted_action_calls': 0, 'reported_input_tokens': 31379, 'reported_output_tokens': 4653, 'reported_cache_tokens': 9856, 'estimated_cost_usd_for_reported_usage': 0.012099636, 'recorded_call_elapsed_seconds': 80.65196541498881}.
