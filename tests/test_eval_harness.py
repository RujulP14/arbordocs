from eval.harness import compute_detection_metrics


def test_perfect_predictions_score_1():
    y_true = [True, True, False, False]
    y_pred = [True, True, False, False]

    precision, recall, f1 = compute_detection_metrics(y_true, y_pred)

    assert precision == 1.0
    assert recall == 1.0
    assert f1 == 1.0


def test_false_positive_lowers_precision_not_recall():
    y_true = [True, False, False]
    y_pred = [True, True, False]

    precision, recall, f1 = compute_detection_metrics(y_true, y_pred)

    assert precision == 0.5
    assert recall == 1.0
    assert 0 < f1 < 1


def test_false_negative_lowers_recall_not_precision():
    y_true = [True, True, False]
    y_pred = [True, False, False]

    precision, recall, f1 = compute_detection_metrics(y_true, y_pred)

    assert precision == 1.0
    assert recall == 0.5
    assert 0 < f1 < 1


def test_no_positives_predicted_is_zero_recall_without_error():
    y_true = [True, True]
    y_pred = [False, False]

    precision, recall, f1 = compute_detection_metrics(y_true, y_pred)

    assert precision == 0.0
    assert recall == 0.0
    assert f1 == 0.0


def test_no_true_positives_in_dataset_does_not_raise():
    y_true = [False, False]
    y_pred = [False, True]

    precision, recall, f1 = compute_detection_metrics(y_true, y_pred)

    assert precision == 0.0
    assert recall == 0.0
    assert f1 == 0.0
