"""Operator question edges read through the held-scope report authority."""


def read_question_states(call, previous_ids, unwrap):
    function = "steering.report.get"
    result = unwrap(
        call(
            function,
            {
                "questions_only": True,
                "previous_question_ids": list(previous_ids),
            },
        ),
        function,
    )
    # Older serving builds omit this field; their scheduled reports still work.
    return {int(key): value for key, value in result.get("question_states", {}).items()}


def question_deltas(previous, current):
    before = previous.questions if previous is not None else {}
    return [
        f"fleet question {key} {status}"
        for key, status in sorted(current.questions.items())
        if before.get(key) != status
    ]
