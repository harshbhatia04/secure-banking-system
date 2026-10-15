import unittest

from ai_fraud import MODEL, risk_score


class AiFraudTrainingTests(unittest.TestCase):
    def test_public_training_artifact_and_score(self):
        self.assertEqual(MODEL['source_name'], 'BankSim synthetic bank payments')
        self.assertGreater(MODEL['training_rows'], 400_000)
        self.assertGreater(MODEL['test_fraud'], 0)
        self.assertGreater(MODEL['average_precision'], 0.5)
        small, _ = risk_score(10_000, 0, True)
        large, _ = risk_score(500_000, 0, True)
        self.assertLess(small, MODEL['threshold'])
        self.assertGreater(large, MODEL['threshold'])


if __name__ == '__main__':
    unittest.main()
