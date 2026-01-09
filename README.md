# Run in a CLI, commands are as follows: 

  # Scan top 20 high-volume markets
  python -m tracker scan

  # Detailed output
  python -m tracker scan --verbose

  # Analyze specific market
  python -m tracker analyze "will-trump-win"

  # Track wallet activity
  python -m tracker wallet 0x1234...

  # List monitored markets
  python -m tracker markets

  # Continuous monitoring (every 15 min)
  python -m tracker watch --interval 15
