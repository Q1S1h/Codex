"""Generate seeded synthetic XPS files; never overwrite existing demo files."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.integrate import cumulative_trapezoid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('analysis_output/demo_v02'))
    args = parser.parse_args()
    names = ['gaussian.csv', 'gaussian.txt', 'gaussian.xlsx']
    args.output.mkdir(parents=True, exist_ok=True)
    if any((args.output/name).exists() for name in names):
        parser.error('Demo files already exist; select a fresh directory')
    x = np.linspace(275, 295, 501)
    peak = 100/(.8*np.sqrt(2*np.pi))*np.exp(-.5*((x-285)/.8)**2)
    integral = cumulative_trapezoid(peak, x, initial=0)
    background = 5+12*integral/integral[-1]
    y = peak+background+np.random.default_rng(42).normal(0, .02, len(x))
    frame = pd.DataFrame({'Binding Energy (eV)': x[::-1], 'Intensity (cps)': y[::-1]})
    frame.to_csv(args.output/names[0], index=False)
    frame.to_csv(args.output/names[1], sep='\t', index=False)
    frame.to_excel(args.output/names[2], index=False)
    print(f'Created {args.output.resolve()}')
    print('Reference: center=285 eV; sigma=0.8 eV; FWHM=1.883856 eV; area=100 cps*eV')


if __name__ == '__main__':
    main()
