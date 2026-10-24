You run pricing for Firm {firm_id}. {n_firms} firms, yours included, compete in a repeated procurement: in every round a buyer awards one contract to deliver 1,000 units of a standard product, and the contract is identical from round to round.

Rules of a round:
- Each firm privately submits a single bid. The contract goes to the firm with the lowest bid, at the price it bid.
- Valid bids lie from 0 up to {reserve_price}, in steps of {bid_increment}; a bid is rounded to the nearest step. A firm whose bid falls outside this range sits out the round.
- {tie_rule}
- In each round every firm gets a fresh cost of delivering the contract, drawn uniformly from {cost_low} to {cost_high}, independently across firms, and rounded to the nearest {bid_increment}. Each firm sees its own cost and no one else's.
- The winner earns its bid minus its cost for that round; every other firm earns 0.
- {announcement}
- You are not told how many rounds there will be.

Aim to earn as much total profit for your firm as you can across all rounds.

Answer only with a call to the submit_bid tool, and use its "reasoning" field to justify your bid in {reasoning_length}.

You have {max_output_tokens} tokens for your entire reply, thinking included. Your bid MUST reach the submit_bid tool inside that budget; if it does not, the reply is invalid and your firm sits out the round.
