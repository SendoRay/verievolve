# M4 hierarchical action proposer smoke

DeepSeek selects only a generic hardware action. A frozen executor expands it to a legal unvisited typed neighbor. Repeated valid actions remain valid while another neighbor exists; invalid or exhausted actions use a recorded least-used deterministic fallback without spending an extra evaluation.

The non-LLM comparator is UCB1 over the same actions and uses the same expansion rule. Every cell has exactly eight new-candidate evaluations. FIR and NCO terminal truth and strict Nangate45 area identities are inherited unchanged from their formal v2 artifacts; no RTL generation or synthesis is performed here.

## FIR

- `ucb1_action:boolean`: 1/1 complete; [0.3862070994139518]
- `ucb1_action:numerical`: 1/1 complete; [0.3862070994139518]
- `deepseek_hierarchical_action:boolean`: 1/1 complete; [0.5638311281867494]
- `deepseek_hierarchical_action:numerical`: 1/1 complete; [0.47910784535154327]

Interaction records: [{'seed': 20261031, 'value': -0.08472328283520614}]; mean -0.08472328283520614.
LLM accounting: {'recorded_calls': 16, 'api_ok_calls': 16, 'repeated_action_proposals': 11, 'fallback_expansions': 0, 'invalid_or_failed_action_calls': 0, 'exhausted_action_calls': 0, 'reported_input_tokens': 9338, 'reported_output_tokens': 1442, 'reported_cache_tokens': 0, 'estimated_cost_usd_for_reported_usage': 0.0045318, 'recorded_call_elapsed_seconds': 26.221986333839595}.

## NCO

- `ucb1_action:boolean`: 1/1 complete; [0.7581126404708671]
- `ucb1_action:numerical`: 1/1 complete; [0.7581126404708671]
- `deepseek_hierarchical_action:boolean`: 1/1 complete; [0.7576031719537616]
- `deepseek_hierarchical_action:numerical`: 1/1 complete; [0.7581126404708671]

Interaction records: [{'seed': 20261021, 'value': 0.000509468517105538}]; mean 0.000509468517105538.
LLM accounting: {'recorded_calls': 16, 'api_ok_calls': 16, 'repeated_action_proposals': 5, 'fallback_expansions': 0, 'invalid_or_failed_action_calls': 0, 'exhausted_action_calls': 0, 'reported_input_tokens': 10484, 'reported_output_tokens': 1465, 'reported_cache_tokens': 1792, 'estimated_cost_usd_for_reported_usage': 0.004376352, 'recorded_call_elapsed_seconds': 27.85574554395862}.
