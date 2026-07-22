class PositionMonitor:
    """
    Hold/exit evaluation for an already-open position. Deliberately does NOT
    re-run DecisionEngine or call the AI advisor - it only checks the live
    Nifty price against the stop_loss/target_1 levels frozen into the
    position at entry-approval time. A dynamic reversal-based early exit is
    an explicit future enhancement, not this version.
    """

    def evaluate(self, position, market):

        price = market["price"]
        snapshot = position["decision_snapshot"]

        stop_loss = snapshot["stop_loss"]
        target_1 = snapshot["target_1"]

        if position["direction"] == "CALL":

            if stop_loss is not None and price <= stop_loss:
                return {"action": "EXIT", "reason": "STOP_LOSS_HIT"}

            if target_1 is not None and price >= target_1:
                return {"action": "EXIT", "reason": "TARGET_HIT"}

        else:

            if stop_loss is not None and price >= stop_loss:
                return {"action": "EXIT", "reason": "STOP_LOSS_HIT"}

            if target_1 is not None and price <= target_1:
                return {"action": "EXIT", "reason": "TARGET_HIT"}

        return {"action": "HOLD", "reason": None}
