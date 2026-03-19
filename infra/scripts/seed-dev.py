"""Seed the development database with sample data."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine
from app.models.analysis import AnalysisRun, RunStatus
from app.models.signals import TradeSignal, TradeDecision, TradingMode

logger = structlog.get_logger()


async def seed():
    async with AsyncSession(engine) as session:
        # Create a sample completed analysis run
        run = AnalysisRun(
            status=RunStatus.COMPLETED,
            top_n=5,
            mode="swing",
            tickers_screened=20,
            signals_generated=5,
        )
        session.add(run)
        await session.flush()

        # Sample signals
        signals = [
            TradeSignal(
                run_id=run.id,
                ticker="AAPL",
                decision=TradeDecision.BUY,
                confidence_score=0.78,
                trading_mode=TradingMode.SWING,
                entry_price=185.50,
                stop_loss_price=179.25,
                stop_loss_method="ATR-2x (ATR=3.125)",
                take_profit_price=198.75,
                risk_reward_ratio=2.2,
                position_size_pct=2.5,
                technical_score=0.82,
                fundamental_score=0.75,
                sentiment_score=0.68,
                catalyst_score=0.80,
                key_risks=["earnings in 8 days", "sector rotation risk"],
                reasoning="Strong technical setup with bullish MACD crossover and high RS.",
                is_paper=True,
            ),
            TradeSignal(
                run_id=run.id,
                ticker="NVDA",
                decision=TradeDecision.BUY,
                confidence_score=0.85,
                trading_mode=TradingMode.SWING,
                entry_price=875.00,
                stop_loss_price=845.00,
                stop_loss_method="ATR-2x (ATR=15.00)",
                take_profit_price=945.00,
                risk_reward_ratio=2.33,
                position_size_pct=2.0,
                technical_score=0.88,
                fundamental_score=0.82,
                sentiment_score=0.85,
                catalyst_score=0.90,
                key_risks=["high valuation", "chip export restrictions"],
                reasoning="AI demand tailwind with strong earnings momentum and analyst upgrades.",
                is_paper=True,
            ),
        ]

        for signal in signals:
            session.add(signal)

        await session.commit()
        logger.info("Seed data created", run_id=str(run.id), signals=len(signals))


if __name__ == "__main__":
    asyncio.run(seed())
