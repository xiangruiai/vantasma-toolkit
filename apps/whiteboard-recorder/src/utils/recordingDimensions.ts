const MIN_RECORDING_DIMENSION = 320;
const MAX_RECORDING_DIMENSION = 7680;

export const toEvenRecordingDimension = (value: number) => {
  const finiteValue = Number.isFinite(value) ? value : MIN_RECORDING_DIMENSION;
  const roundedValue = Math.round(finiteValue);
  const clampedValue = Math.min(
    MAX_RECORDING_DIMENSION,
    Math.max(MIN_RECORDING_DIMENSION, roundedValue),
  );

  return clampedValue % 2 === 0
    ? clampedValue
    : Math.min(MAX_RECORDING_DIMENSION, clampedValue + 1);
};

export const normalizeRecordingDimensions = (dimensions: { width: number; height: number }) => ({
  width: toEvenRecordingDimension(dimensions.width),
  height: toEvenRecordingDimension(dimensions.height),
});
