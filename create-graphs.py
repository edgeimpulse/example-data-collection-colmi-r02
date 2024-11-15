import argparse
import pandas as pd
import matplotlib.pyplot as plt
import os

def remove_outliers(df, column):
    # Calculate the IQR for the specified column
    Q1 = df[column].quantile(0.25)
    Q3 = df[column].quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR

    # Filter the DataFrame to remove outliers
    return df[(df[column] >= lower_bound) & (df[column] <= upper_bound)]

def plot_data(input_file, column, remove_outliers_flag):
    # Load the CSV file into a DataFrame
    df = pd.read_csv(input_file, parse_dates=['timestamp'])
    
    # Check if the column exists in the DataFrame
    if column not in df.columns:
        print(f"Error: Column '{column}' not found in {input_file}.")
        print("Available columns:", df.columns.tolist())
        return

    # Drop NaN values for the specified column
    df = df.dropna(subset=[column])

    # Remove outliers if the flag is set
    if remove_outliers_flag:
        df = remove_outliers(df, column)

    # Create graphs folder if it doesn't exist
    os.makedirs("graphs", exist_ok=True)

    # Extract the base filename without extension
    base_filename = os.path.splitext(os.path.basename(input_file))[0]

    # Define the output path for the graph image
    output_path = f"graphs/{base_filename}_{column}.png"

    # Plot the data
    plt.figure(figsize=(10, 6))
    plt.plot(df['timestamp'], df[column], label=column, color='b')
    plt.title(f"{column} over Time" + (" (Outliers Removed)" if remove_outliers_flag else ""))
    plt.xlabel("Timestamp")
    plt.ylabel(column)
    plt.xticks(rotation=45)
    plt.legend()
    plt.tight_layout()

    # Save the plot to the specified output path
    plt.savefig(output_path)
    print(f"Graph saved to {output_path}")
    # plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot data from CSV file")
    parser.add_argument("--input", required=True, help="Path to the CSV file")
    parser.add_argument("--column", required=True, help="Column name to plot")
    parser.add_argument("--keep-outliers", action="store_false", dest="remove_outliers", help="Keep outliers in the data")

    args = parser.parse_args()

    # Call plot_data with the remove_outliers argument as True by default unless --keep-outliers is specified
    plot_data(args.input, args.column, args.remove_outliers)
